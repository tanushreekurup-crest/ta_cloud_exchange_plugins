"""
BSD 3-Clause License

Copyright (c) 2021, Netskope OSS
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

CRE Forescout Cloud Security plugin helper module.
"""

import json
import re
import time
import traceback
from typing import Dict, Tuple, Union

import requests
from netskope.common.utils import add_user_agent

from .constants import (
    DEFAULT_WAIT_TIME,
    MAX_API_CALLS,
    MODULE_NAME,
    PLATFORM_NAME,
    PLUGIN_NAME,
)


class ForescoutPluginException(Exception):
    """Forescout plugin custom exception class."""

    pass


class ForescoutPluginHelper(object):
    """ForescoutPluginHelper Class.

    Args:
        object (object): Object class.
    """

    def __init__(
        self,
        logger,
        log_prefix: str,
        plugin_name: str,
        plugin_version: str,
        configuration: Dict,
    ):
        """ForescoutPluginHelper initializer.

        Args:
            logger (logger object): Logger object.
            log_prefix (str): Log prefix.
            plugin_name (str): Plugin name.
            plugin_version (str): Plugin version.
            ssl_validation : SSL Validation Flag.
            proxy : Proxy Configuration.
            configuration (Dict): Configuration parameters dictionary.
        """
        self.logger = logger
        self.log_prefix = log_prefix
        self.plugin_name = plugin_name
        self.plugin_version = plugin_version
        self.configuration = configuration

    def _add_user_agent(self, headers: Union[Dict, None] = None) -> Dict:
        """Add User-Agent in the headers for third-party requests.
        Args:
            headers (Dict): Dictionary containing headers for any request.
        Returns:
            Dict: Dictionary after adding User-Agent.
        """
        if headers and "User-Agent" in headers:
            return headers

        headers = add_user_agent(headers)
        ce_added_agent = headers.get("User-Agent", "netskope-ce")
        user_agent = "{}-{}-{}-v{}".format(
            ce_added_agent,
            MODULE_NAME.lower(),
            self.plugin_name.lower().replace(" ", "-"),
            self.plugin_version,
        )
        headers.update({"User-Agent": user_agent})
        return headers

    def api_helper(
        self,
        logger_msg: str,
        url: str,
        method: str = "GET",
        params: Dict = {},
        data=None,
        files=None,
        headers: Dict = {},
        json=None,
        is_handle_error_required=True,
        is_validation: bool = False,
        regenerate_auth_token: bool = True,
        verify: bool = True,
        proxies: Dict = {},
        show_params: bool = True,
        show_data: bool = True,
    ):
        """API Helper perform API request to ThirdParty platform
        and captures all the possible errors for requests.

        Args:
            logger_msg (str): Logger message.
            url (str): API Endpoint.
            method (str): Method for the endpoint.
            params (Dict, optional): Request parameters dictionary.
            Defaults to None.
            data (Any,optional): Data to be sent to API. Defaults to None.
            headers (Dict, optional): Headers for the request. Defaults to {}.
            json (optional): Json payload for request. Defaults to None.
            is_handle_error_required (bool, optional): Does the API helper
            should handle the status codes. Defaults to True.
            is_validation (bool, optional): Does this request coming from
            validate method?. Defaults to False.
            regenerate_auth_token (bool, optional): Is regenerating auth token
            required? Defaults to True.


        Returns:
            Response|Response JSON: Returns response json if
            is_handle_error_required is True otherwise returns Response object.
        """
        try:
            headers = self._add_user_agent(headers)

            debug_log_msg = (
                f"{self.log_prefix}: API Request for {logger_msg}."
                f" Endpoint: {method} {url}"
            )
            if params and show_params:
                debug_log_msg += f", params: {params}"
            if data and show_data:
                debug_log_msg += f", data: {data}."
            if json and show_data:
                debug_log_msg += f", json: {json}."

            self.logger.debug(debug_log_msg)
            for retry_counter in range(MAX_API_CALLS):
                response = requests.request(
                    url=url,
                    method=method,
                    params=params,
                    data=data,
                    headers=headers,
                    verify=verify,
                    proxies=proxies,
                    json=json,
                    files=files,
                )
                status_code = response.status_code
                self.logger.debug(
                    f"{self.log_prefix}: Received API Response for "
                    f"{logger_msg}. Status Code={status_code}."
                )
                if (
                    status_code == 401
                    and regenerate_auth_token
                    and not is_validation
                ):
                    base_url, username, password = self.get_credentials(
                        configuration=self.configuration
                    )
                    auth_header = self.get_auth_header(
                        username,
                        password,
                        base_url,
                        verify,
                        proxies,
                        is_validation,
                    )
                    headers.update(auth_header)
                    return self.api_helper(
                        url=url,
                        method=method,
                        params=params,
                        headers=headers,
                        json=json,
                        files=files,
                        data=data,
                        is_handle_error_required=is_handle_error_required,
                        is_validation=is_validation,
                        logger_msg=logger_msg,
                        regenerate_auth_token=False,
                        proxies=proxies,
                        verify=verify,
                    )

                if (
                    response.status_code == 429
                    or 500 <= response.status_code <= 600
                ) and not is_validation:
                    if retry_counter == MAX_API_CALLS - 1:
                        err_msg = (
                            f"Received exit code {response.status_code}, While"
                            f" {logger_msg}. Max retries for rate limit "
                            "handler exceeded hence returning status"
                            f" code {response.status_code}."
                        )
                        self.logger.error(
                            message=f"{self.log_prefix}: {err_msg}",
                            details=f"API response: {response.text}",
                        )
                        raise ForescoutPluginException(err_msg)
                    self.logger.error(
                        message=(
                            "{}: Received exit code {}, While"
                            " {}. Retrying after {} "
                            "seconds. {} retries remaining.".format(
                                self.log_prefix,
                                response.status_code,
                                logger_msg,
                                DEFAULT_WAIT_TIME,
                                MAX_API_CALLS - 1 - retry_counter,
                            )
                        ),
                        details=f"API response: {response.text}",
                    )
                    time.sleep(DEFAULT_WAIT_TIME)
                else:
                    return (
                        self.handle_error(response, logger_msg, is_validation)
                        if is_handle_error_required
                        else response
                    )
        except ForescoutPluginException:
            raise
        except requests.exceptions.ProxyError as error:
            err_msg = (
                f"Proxy error occurred while {logger_msg}. Verify the"
                " proxy configuration provided."
            )
            if is_validation:
                err_msg = (
                    "Proxy error occurred. Verify "
                    "the proxy configuration provided."
                )

            self.logger.error(
                message=(
                    f"{self.log_prefix}: {err_msg} "
                    f"Error: {self.remove_sensitive_info(str(error))}"
                ),
                details=self.remove_sensitive_info(traceback.format_exc()),
            )
            raise ForescoutPluginException(err_msg)
        except requests.exceptions.ConnectionError as error:
            err_msg = (
                f"Unable to establish connection with {PLATFORM_NAME} "
                f"platform while {logger_msg}. Proxy server or "
                f"{PLATFORM_NAME} server is not reachable."
            )
            if is_validation:
                err_msg = (
                    f"Unable to establish connection with {PLATFORM_NAME} "
                    f"platform. Proxy server or {PLATFORM_NAME}"
                    " server is not reachable."
                )

            self.logger.error(
                message=(
                    f"{self.log_prefix}: {err_msg} "
                    f"Error: {self.remove_sensitive_info(str(error))}"
                ),
                details=self.remove_sensitive_info(traceback.format_exc()),
            )

            raise ForescoutPluginException(err_msg)
        except requests.HTTPError as err:
            err_msg = f"HTTP error occurred while {logger_msg}."
            if is_validation:
                err_msg = (
                    "HTTP error occurred. Verify"
                    " configuration parameters provided."
                )
            self.logger.error(
                message=(
                    f"{self.log_prefix}: {err_msg} "
                    f"Error: {self.remove_sensitive_info(str(err))}"
                ),
                details=self.remove_sensitive_info(traceback.format_exc()),
            )
            raise ForescoutPluginException(err_msg)
        except Exception as exp:
            err_msg = f"Unexpected error occurred while {logger_msg}."
            if is_validation:
                err_msg = (
                    "Unexpected error while performing "
                    f"API call to {PLATFORM_NAME}."
                )
                self.logger.error(
                    message=(
                        f"{self.log_prefix}: {err_msg} Error:"
                        f" {self.remove_sensitive_info(str(exp))}"
                    ),
                    details=self.remove_sensitive_info(traceback.format_exc()),
                )
                raise ForescoutPluginException(
                    f"{err_msg} Check logs for more details."
                )
            self.logger.error(
                message=(
                    f"{self.log_prefix}: {err_msg} Error:"
                    f" {self.remove_sensitive_info(str(exp))}"
                ),
                details=self.remove_sensitive_info(traceback.format_exc()),
            )
            raise ForescoutPluginException(err_msg)

    def parse_response(
        self, response: requests.models.Response, is_validation: bool = False
    ):
        """Parse Response will return JSON from response object.

        Args:
            response (response): Response object.

        Returns:
            Any: Response Json.
        """
        try:
            return response.json()
        except json.JSONDecodeError as err:
            err_msg = (
                f"Invalid JSON response received from API. Error: {str(err)}"
            )
            self.logger.error(
                message=f"{self.log_prefix}: {err_msg}",
                details=f"API response: {response.text}",
            )
            if is_validation:
                err_msg = (
                    "Verify Base URL provided in the "
                    "configuration parameters. Check logs for more details."
                )
            raise ForescoutPluginException(err_msg)
        except Exception as exp:
            err_msg = (
                "Unexpected error occurred while parsing"
                f" json response. Error: {exp}"
            )
            self.logger.error(
                message=f"{self.log_prefix}: {err_msg}",
                details=f"API response: {response.text}",
            )
            if is_validation:
                err_msg = (
                    "Unexpected validation error occurred, "
                    "Verify Base URL provided in the "
                    "configuration parameters. Check logs for more details."
                )
            raise ForescoutPluginException(err_msg)

    def handle_error(
        self,
        resp: requests.models.Response,
        logger_msg: str,
        is_validation: bool = False,
    ):
        """Handle the different HTTP response code.

        Args:
            resp (requests.models.Response): Response object
            returned from API call.
            logger_msg: logger message.
            is_validation : API call from validation method or not
        Returns:
            dict: Returns the dictionary of response JSON
            when the response code is 200.
        Raises:
            HTTPError: When the response code is not 200.
        """
        status_code = resp.status_code
        validation_msg = "Validation error occurred, "
        error_dict = {
            400: "Received exit code 400, HTTP client error",
            403: "Received exit code 403, Forbidden",
            401: "Received exit code 401, Unauthorized access",
            404: "Received exit code 404, Resource not found",
        }
        if is_validation:
            error_dict = {
                400: (
                    "Received exit code 400, Bad Request, Verify the "
                    " Base URL, Username and Password provided in the"
                    " configuration parameters."
                ),
                401: (
                    "Received exit code 401, Unauthorized, Verify "
                    "Username and Password provided in the "
                    "configuration parameters."
                ),
                403: (
                    "Received exit code 403, Forbidden, Verify "
                    "Username and Password provided in the "
                    "configuration parameters."
                ),
                404: (
                    "Received exit code 404, Resource not found, Verify "
                    "Base URL provided in the configuration parameters."
                ),
            }

        if status_code in [200, 201]:
            return self.parse_response(
                response=resp, is_validation=is_validation
            )
        elif status_code == 204:
            return {}
        elif status_code in error_dict:
            err_msg = error_dict[status_code]
            if is_validation:
                log_err_msg = validation_msg + err_msg
                self.logger.error(
                    message=f"{self.log_prefix}: {log_err_msg}",
                    details=f"API response: {resp.text}",
                )
                raise ForescoutPluginException(err_msg)
            else:
                err_msg = err_msg + " while " + logger_msg + "."
                self.logger.error(
                    message=f"{self.log_prefix}: {err_msg}",
                    details=f"API response: {resp.text}",
                )
                raise ForescoutPluginException(err_msg)

        else:
            err_msg = (
                "HTTP Server Error"
                if (status_code >= 500 and status_code <= 600)
                else "HTTP Error"
            )
            self.logger.error(
                message=(
                    f"{self.log_prefix}: Received exit code {status_code}, "
                    f"{validation_msg+err_msg} while {logger_msg}."
                ),
                details=f"API response: {resp.text}",
            )
            raise ForescoutPluginException(err_msg)

    def get_auth_header(
        self,
        username,
        password,
        base_url,
        verify=True,
        proxies={},
        is_validation=False,
    ):
        """Get the OAUTH2 Json object with access token from Forescout
        platform.

        Args:
            Username (str): Username required to generate OAUTH2 token.
            Password (str): Client Secret required to generate OAUTH2
            token.
            base_url (str): Base URL of Forescout.
            is_validation (bool): Is this a validation call?
        Returns:
            json: JSON response data in case of Success.
        """
        auth_endpoint = f"{base_url}/api/login"
        auth_params = {
            "username": username,
            "password": password,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            response = self.api_helper(
                method="POST",
                url=auth_endpoint,
                headers=headers,
                params=auth_params,
                logger_msg=f"getting auth token from {PLUGIN_NAME}",
                is_handle_error_required=False,
                show_params=False,
                proxies=proxies,
                verify=verify,
            )
            if response.status_code in [200, 201]:
                # Returns the access token from response text.
                if response.text:
                    return {"Authorization": response.text}
                else:
                    err_msg = (
                        "Invalid authentication token received"
                        f" from {PLATFORM_NAME}."
                    )
                    if is_validation:
                        err_msg = (
                            f"{err_msg} Verify the Base URL, Username and"
                            " Password provided in the configuration"
                            " parameters."
                        )

                    self.logger.error(
                        message=f"{self.log_prefix}: {err_msg}",
                        details=f"API response: {response.text}",
                    )
                    raise ForescoutPluginException(err_msg)
            else:
                return self.handle_error(response, "getting auth token", True)
        except ForescoutPluginException:
            raise
        except Exception as exp:
            if is_validation:
                err_msg = (
                    "Unexpected validation error occurred "
                    "while authenticating."
                )
                self.logger.error(
                    message=f"{self.log_prefix}: {err_msg} Error: {exp}",
                    details=traceback.format_exc(),
                )
                raise ForescoutPluginException(
                    f"{err_msg} Check logs for more details."
                )
            err_msg = "Unexpected error occurred while getting auth token."
            self.logger.error(
                message=f"{self.log_prefix}: {err_msg} Error: {exp}",
                details=traceback.format_exc(),
            )
            raise ForescoutPluginException(err_msg)

    def get_credentials(self, configuration: Dict) -> Tuple:
        """Get API Credentials.

        Args:
            configuration (Dict): Configuration dictionary.

        Returns:
            Tuple: Tuple containing Base URL, Client ID and Client Secret.
        """
        return (
            configuration.get("base_url", "").strip().strip("/"),
            configuration.get("username", "").strip(),
            configuration.get("password"),
        )

    def remove_sensitive_info(self, data: Dict) -> Dict:
        """Remove sensitive data from data dictionary.

        Args:
            data (Dict): Data dictionary.

        Returns:
            Dict: Data dictionary with sensitive information removed.
        """
        filtered_traceback = re.sub(
            r"password=[^&\s]+", "password=<Password>", data
        )
        return filtered_traceback