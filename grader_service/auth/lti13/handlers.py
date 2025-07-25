import base64
import hashlib
import json
import re
import uuid
from typing import Any, Dict, Optional, cast
from urllib.parse import quote, unquote

from oauthlib.common import generate_token
from tornado.httputil import url_concat
from tornado.log import app_log
from tornado.web import HTTPError, MissingArgumentError, RequestHandler

from grader_service.handlers.base_handler import BaseHandler
from grader_service.utils import convert_request_to_dict, url_path_join

from .error import InvalidAudienceError, LoginError, ValidationError
from .validator import LTI13LaunchValidator

STATE_COOKIE_NAME = "grader-lti13authenticator-state"
NONCE_STATE_COOKIE_NAME = "grader-lti13authenticator-nonce-state"


def make_nonce_state() -> str:
    """
    Create state for nonce calculation.
    """
    return generate_token(length=64)


def get_nonce(nonce_state: str) -> str:
    """
    Create a nonce by hashing state.

    SHA 256 is used to create the hash. The nonce is its hexdigest.
    """
    hash = hashlib.sha256(nonce_state.encode())
    nonce = hash.hexdigest()
    return nonce


def _serialize_state(state):
    """Serialize OAuth state to a base64 string after passing through JSON"""
    json_state = json.dumps(state)
    return base64.urlsafe_b64encode(json_state.encode("utf8")).decode("ascii")


def _deserialize_state(b64_state):
    """Deserialize OAuth state as serialized in _serialize_state"""
    if isinstance(b64_state, str):
        b64_state = b64_state.encode("ascii")
    try:
        json_state = base64.urlsafe_b64decode(b64_state).decode("utf8")
    except ValueError:
        app_log.error(f"Failed to b64-decode state: {b64_state}")
        return {}
    try:
        return json.loads(json_state)
    except ValueError:
        app_log.error(f"Failed to json-decode state: {json_state}")
        return {}


class LTI13ConfigHandler(BaseHandler):
    """
    Handles JSON configuration file for LTI 1.3.
    """

    async def get(self) -> None:
        """
        Gets the JSON config which is used by LTI platforms
        to install the external tool.

        - The extensions key contains settings for specific vendors, such as canvas,
        moodle, edx, among others.
        - The tool uses public settings by default. Users that wish to install the tool with
        private settings should either copy/paste the json or toggle the application to private
        after it is installed with the platform.
        - Usernames are obtained by first attempting to get and normalize values sent when
        tools are installed with public settings. If private, the username is set using the
        anonumized user data when requests are sent with private installation settings.
        """
        self.set_header("Content-Type", "application/json")

        # get the origin protocol
        protocol = self.authenticator.get_uri_scheme(self.request)
        self.log.debug(f"Origin protocol is: {protocol}")
        # build the full target link url value required for the jwks endpoint
        target_link_url = f"{protocol}://{self.request.host}"
        self.log.debug(f"Target link url is: {target_link_url}")
        keys = {
            "title": self.authenticator.tool_name,
            "scopes": [
                "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
                "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem.readonly",
                "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
                "https://purl.imsglobal.org/spec/lti-ags/scope/score",
                "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly",
                "https://canvas.instructure.com/lti/public_jwk/scope/update",
                "https://canvas.instructure.com/lti/data_services/scope/create",
                "https://canvas.instructure.com/lti/data_services/scope/show",
                "https://canvas.instructure.com/lti/data_services/scope/update",
                "https://canvas.instructure.com/lti/data_services/scope/list",
                "https://canvas.instructure.com/lti/data_services/scope/destroy",
                "https://canvas.instructure.com/lti/data_services/scope/list_event_types",
                "https://canvas.instructure.com/lti/feature_flags/scope/show",
                "https://canvas.instructure.com/lti/account_lookup/scope/show",
            ],
            "extensions": [
                {
                    "platform": "canvas.instructure.com",
                    "settings": {
                        "platform": "canvas.instructure.com",
                        "placements": [
                            {
                                "placement": "course_navigation",
                                "message_type": "LtiResourceLinkRequest",
                                "windowTarget": "_blank",
                                "target_link_uri": target_link_url,
                                "custom_fields": {
                                    "email": "$Person.email.primary",
                                    "lms_user_id": "$User.id",
                                },
                            },
                            {
                                "placement": "assignment_selection",
                                "message_type": "LtiResourceLinkRequest",
                                "target_link_uri": target_link_url,
                            },
                        ],
                    },
                    "privacy_level": "public",
                }
            ],
            "description": self.authenticator.tool_description,
            "custom_fields": {"email": "$Person.email.primary", "lms_user_id": "$User.id"},
            "target_link_uri": target_link_url,
            "oidc_initiation_url": self.authenticator.login_url(
                url_path_join(target_link_url, self.hub.server.base_url)
            ),
        }
        self.write(json.dumps(keys))


class LTI13LoginInitHandler(BaseHandler):
    """
    Handles JupyterHub authentication requests according to the
    LTI 1.3 standard.
    """

    _state = None

    def check_xsrf_cookie(self):
        """
        Do not attempt to check for xsrf parameter in POST requests. LTI requests are
        meant to be cross-site, so it must not be verified.
        """
        return

    def authorize_redirect(
        self,
        redirect_uri: str,
        login_hint: str,
        nonce: str,
        client_id: str,
        state: str,
        lti_message_hint: Optional[str] = None,
    ) -> None:
        """
        Overrides the OAuth2Mixin.authorize_redirect method to to initiate the LTI 1.3 / OIDC
        login flow with the required and optional arguments.

        User Agent (browser) is redirected to the platform's authorization url for further
        processing.

        References:
        https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest
        http://www.imsglobal.org/spec/lti/v1p3/#additional-login-parameters-0

        Args:
          redirect_uri: redirect url specified during tool installation (callback url) to
            which the user will be redirected from the platform after attempting authorization.
          login_hint: opaque value used by the platform for user identity
          nonce: unique value sent to allow recipients to protect themselves against replay attacks
          client_id: used to identify the tool's installation with a platform
          state: opaque value for the platform to maintain state between the request and
            callback and provide Cross-Site Request Forgery (CSRF) mitigation.
          lti_message_hint: similarly to the login_hint parameter, lti_message_hint value is opaque to the tool.
            If present in the login initiation request, the tool MUST include it back in
            the authentication request unaltered.
        """
        handler = cast(RequestHandler, self)
        # Required parameter with values specified by LTI 1.3
        # https://www.imsglobal.org/spec/security/v1p0/#step-2-authentication-request
        args = {
            "response_type": "id_token",
            "scope": "openid",
            "response_mode": "form_post",
            "prompt": "none",
        }
        # Dynamically computed required parameter values
        args["client_id"] = client_id
        args["redirect_uri"] = redirect_uri
        args["login_hint"] = login_hint
        args["nonce"] = nonce
        args["state"] = state

        if lti_message_hint is not None:
            args["lti_message_hint"] = lti_message_hint

        url = self.authenticator.authorize_url
        handler.redirect(url_concat(url, args))

    def get_state(self):
        next_url = original_next_url = self.get_argument("next", None)
        if not next_url:
            # try with the target_link_uri arg
            target_link = self.get_argument("target_link_uri", "")
            if "next" in target_link:
                self.log.debug(f"Trying to get the next-url from target_link_uri: {target_link}")
                next_search = re.search("next=(.*)", target_link, re.IGNORECASE)
                if next_search:
                    next_url = next_search.group(1)
                    # decode the some characters obtained with the link builder
                    next_url = unquote(next_url)
            elif not target_link.endswith("/hub"):
                next_url = target_link
        if next_url:
            # Note: allow hostname-having urls
            # avoid browsers treating \ as /
            next_url = next_url.replace("\\", quote("\\"))
            if next_url != original_next_url:
                self.log.warning("Ignoring next_url %r, using %r", original_next_url, next_url)
        if self._state is None:
            self._state = _serialize_state({"state_id": uuid.uuid4().hex, "next_url": next_url})
        return self._state

    async def post(self):
        """
        Validates required login arguments sent from platform and then uses the authorize_redirect() method
        to redirect users to the authorization url.
        """
        validator = LTI13LaunchValidator()
        args = convert_request_to_dict(self.request.arguments)
        self.log.debug(f"Initial login request args are {args}")

        # Raises HTTP 400 if login request arguments are not valid
        try:
            validator.validate_login_request(args)
        except ValidationError as e:
            self.log.error(str(e))
            html = await self.render_template("auth/lti_no_auth.html.j2")
            await self.finish(html)
            return

        login_hint = args["login_hint"]
        self.log.debug(f"login_hint is {login_hint}")

        lti_message_hint = self._get_optional_arg(args, "lti_message_hint")
        client_id = self._get_optional_arg(args, "client_id")

        # lti_deployment_id is not used anywhere. It may be used in the future to influence the
        # login flow depending on the deployment settings. A configurable hook, similar to `Authenticator`'s `post_auth_hook`
        # would be a good way to implement this.
        # lti_deployment_id = self._get_optional_arg(args, "lti_deployment_id")

        redirect_uri = self.get_redirect_uri()
        self.log.debug(f"redirect_uri is: {redirect_uri}")

        # to prevent CSRF
        state = self.generate_state()

        # to prevent replay attacks
        nonce = self.generate_nonce()
        self.log.debug(f"nonce value: {nonce}")

        self.authorize_redirect(
            client_id=client_id,
            login_hint=login_hint,
            lti_message_hint=lti_message_hint,
            nonce=nonce,
            redirect_uri=redirect_uri,
            state=state,
        )

    # GET requests are also allowed by the OpenID Connect launch flow:
    # https://www.imsglobal.org/spec/security/v1p0/#fig_oidcflow
    #
    get = post

    def generate_state(self):
        """Produce a state including the url of the original request."""
        state = self.get_state()
        self.set_state_cookie(state)
        return state

    def generate_nonce(self):
        """Produce a nonce.

        The nonce state will be stored as a session cookie to later validate the nonce
        field of the id_token.
        """
        nonce_state = make_nonce_state()
        self.set_nonce_state_cookie(nonce_state)
        nonce = get_nonce(nonce_state)
        return nonce

    def get_redirect_uri(self) -> str:
        """Create uri to redirect user agent to after successful authorization by the LMS platform."""
        return "{proto}://{host}{path}".format(
            proto=self.authenticator.get_uri_scheme(self.request),
            host=self.request.host,
            path=self.authenticator.callback_url(self.application.base_url),
        )

    def _get_optional_arg(self, args: Dict[str, str], arg: str) -> Optional[str]:
        """
        Return value of optional argument or None if not present.
        """
        value = args.get(arg)
        if value:
            self.log.debug(f"{arg} is {value}")
        else:
            self.log.debug(f"{arg} not present in login initiation request")
        return value

    def set_nonce_state_cookie(self, nonce_state):
        self._set_oauth_cookie(NONCE_STATE_COOKIE_NAME, nonce_state)

    def set_state_cookie(self, state):
        self._set_oauth_cookie(STATE_COOKIE_NAME, state)

    def _set_oauth_cookie(self, key: str, value):
        self._set_cookie(key, value, expires_days=1, httponly=True, encrypted=True)


class LTI13CallbackHandler(BaseHandler):
    """
    Handles JupyterHub authentication requests responses according to the
    LTI 1.3 standard.

    References:
    https://www.imsglobal.org/spec/security/v1p0/#step-3-authentication-response
    https://www.imsglobal.org/spec/security/v1p0/#step-4-resource-is-displayed
    """

    _state_cookie = None
    _nonce_state_cookie = None

    def check_xsrf_cookie(self):
        """
        Do not attempt to check for xsrf parameter in POST requests. LTI requests are
        meant to be cross-site, so it must not be verified.
        """
        return

    async def get(self):
        """Overrides the upstream get handler and always raise HTTPError 405."""
        raise HTTPError(405, "GET method is not allowed for launch requests")

    async def post(self):
        """
        Overrides the upstream post handler.
        """
        try:
            id_token = self.decode_and_validate_launch_request()
        except InvalidAudienceError as e:
            raise HTTPError(401, reason=str(e))
        except ValidationError as e:
            raise HTTPError(400, reason=str(e))

        try:
            user = await self.login_user(id_token)
        except LoginError as e:
            raise HTTPError(400, reason=str(e))
        self.log.debug(f"user logged in: {user}")
        if user is None:
            raise HTTPError(403, reason="User missing or null")
        await self.redirect_to_next_url(user)

    async def redirect_to_next_url(self, user):
        """Redirect user agent to next url that has been received in the login initiation request."""
        next_url = self.get_next_url(user)
        self.redirect(next_url)
        self.log.debug(f"Redirecting user {user.name} to {next_url}")

    def decode_and_validate_launch_request(self) -> Dict[str, Any]:
        """Decrypt, verify and validate launch request parameters.

        Raises subclasses of `ValidationError` of `HTTPError` if anything fails.

        References:
        https://openid.net/specs/openid-connect-core-1_0.html#IDToken
        https://openid.net/specs/openid-connect-core-1_0.html#ImplicitIDTValidation
        """
        validator = LTI13LaunchValidator()

        args = convert_request_to_dict(self.request.arguments)
        self.log.debug(f"Initial launch request args are {args}")

        validator.validate_auth_response(args)

        # Check is state is the same as in the authorization request issued
        # constructed in `LTI13LoginInitHandler.post`, prevents CSRF
        self.check_state()

        id_token = validator.verify_and_decode_jwt(
            encoded_jwt=args.get("id_token"),
            issuer=self.authenticator.issuer,
            audience=self.authenticator.client_id,
            jwks_endpoint=self.authenticator.jwks_endpoint,
            jwks_algorithms=self.authenticator.jwks_algorithms,
        )
        validator.validate_id_token(id_token)
        validator.validate_azp_claim(id_token, self.authenticator.client_id)

        # Check nonce matches the one that has been used in the authorization request.
        # A nonce is a hash of random state which is stored in a session cookie before
        # redirecting to make authorization request. This mitigates replay attacks.
        #
        # References:
        # https://openid.net/specs/openid-connect-core-1_0.html#NonceNotes
        # https://auth0.com/docs/get-started/authentication-and-authorization-flow/mitigate-replay-attacks-when-using-the-implicit-flow
        self.check_nonce(id_token)

        return id_token

    def check_state(self):
        """Verify OAuth state

        compare value in cookie with redirect url param
        """
        cookie_state = self._get_state_cookie()
        if not cookie_state:
            raise HTTPError(400, reason="OAuth state missing from cookies")
        url_state = self._get_state_from_url()
        if cookie_state != url_state:
            self.log.warning(f"OAuth state mismatch: {cookie_state} != {url_state}")
            raise HTTPError(400, reason="OAuth state mismatch")

    def check_nonce(self, id_token: Dict[str, Any]) -> None:
        """Check if received nonce corresponds to hash of nonce state cookie"""
        received_nonce = id_token.get("nonce")

        nonce_state = self._get_nonce_state_cookie()
        if not nonce_state:
            raise HTTPError(400, reason="Missing nonce state cookie")

        nonce = get_nonce(nonce_state)

        if nonce != received_nonce:
            self.log.warning("OAuth nonce mismatch: %s != %s", nonce, received_nonce)
            raise HTTPError(400, reason="OAuth nonce mismatch")

    def get_next_url(self, user=None):
        """Get the redirect target from the state field"""
        state = self._get_state_from_url()
        next_url = _deserialize_state(state).get("next_url")
        if next_url:
            return next_url
        # JupyterHub 0.8 adds default .get_next_url for a fallback
        return super().get_next_url(user)

    def _get_state_from_url(self):
        """Get OAuth state from URL parameters

        Raises HTTPError(400) if `state` argument is missing from request.
        """
        try:
            return self.get_argument("state")
        except MissingArgumentError:
            raise HTTPError(400, reason="OAuth state missing from URL")

    def _get_nonce_state_cookie(self):
        """Get OAuth nonce state from cookies

        To be compared with the value in id_token
        """
        if self._nonce_state_cookie is None:
            self._nonce_state_cookie = self._get_oauth_cookie(NONCE_STATE_COOKIE_NAME)
        return self._nonce_state_cookie

    def _get_state_cookie(self):
        """Get OAuth state from cookies

        To be compared with the value in redirect URL
        """
        if self._state_cookie is None:
            self._state_cookie = self._get_oauth_cookie(STATE_COOKIE_NAME)
        return self._state_cookie

    def _get_oauth_cookie(self, name: str):
        """Get OAuth state cookie."""
        cookie = (self.get_secure_cookie(name) or b"").decode("utf8", "replace")
        self.clear_cookie(name)
        return cookie
