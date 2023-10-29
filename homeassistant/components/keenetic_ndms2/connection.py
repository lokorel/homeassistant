import logging
import re
from re import Match, Pattern
from telnetlib import Telnet
from typing import List, Union

_LOGGER = logging.getLogger(__name__)


class ConnectionException(Exception):
    pass


class Connection:
    @property
    def connected(self) -> bool:
        raise NotImplementedError("Should have implemented this")

    def connect(self):
        raise NotImplementedError("Should have implemented this")

    def disconnect(self):
        raise NotImplementedError("Should have implemented this")

    def run_command(self, command: str) -> List[str]:
        raise NotImplementedError("Should have implemented this")


class TelnetConnection(Connection):
    """Maintains a Telnet connection to a router."""

    def __init__(
        self, host: str, port: int, username: str, password: str, *, timeout: int = 30
    ):
        """Initialize the Telnet connection properties."""
        self._telnet = None  # type: Telnet
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout = timeout
        self._current_prompt_string = None  # type: bytes

    @property
    def connected(self):
        return self._telnet is not None

    def run_command(self, command, *, group_change_expected=False) -> List[str]:
        """Run a command through a Telnet connection.
        Connect to the Telnet server if not currently connected, otherwise
        use the existing connection.
        """
        if not self._telnet:
            self.connect()

        try:
            self._telnet.read_very_eager()  # this is here to flush the read buffer
            self._telnet.write(f"{command}\n".encode())
            response = self._read_response(group_change_expected)
        except Exception as e:
            message = "Error executing command: %s" % str(e)
            _LOGGER.error(message)
            self.disconnect()
            raise ConnectionException(message) from None
        else:
            _LOGGER.debug("Command %s: %s", command, "\n".join(response))
            return response

    def connect(self):
        """Connect to the Telnet server."""
        try:
            self._telnet = Telnet()
            self._telnet.set_option_negotiation_callback(
                TelnetConnection.__negotiate_naws
            )
            self._telnet.open(self._host, self._port, self._timeout)

            self._read_until(b"Login: ")
            self._telnet.write((self._username + "\n").encode("UTF-8"))
            self._read_until(b"Password: ")
            self._telnet.write((self._password + "\n").encode("UTF-8"))

            self._read_response(True)
            self._set_max_window_size()
        except Exception as e:
            message = "Error connecting to telnet server: %s" % str(e)
            _LOGGER.error(message)
            self._telnet = None
            raise ConnectionException(message) from None

    def disconnect(self):
        """Disconnect the current Telnet connection."""
        try:
            if self._telnet:
                self._telnet.write(b"exit\n")
        except Exception as e:
            _LOGGER.error("Telnet error on exit: %s" % str(e))
            pass
        self._telnet = None

    def _read_response(self, detect_new_prompt_string=False) -> List[str]:
        needle = (
            re.compile(rb"\n\(\w+[-\w]+\)>")
            if detect_new_prompt_string
            else self._current_prompt_string
        )
        (match, text) = self._read_until(needle)
        if detect_new_prompt_string:
            self._current_prompt_string = match[0]
        return text.decode("UTF-8").split("\n")[1:-1]

    def _read_until(self, needle: Union[bytes, Pattern]) -> (Match, bytes):
        matcher = needle if isinstance(needle, Pattern) else re.escape(needle)
        (i, match, text) = self._telnet.expect([matcher], self._timeout)
        assert i == 0, "No expected response from server"
        return match, text

    # noinspection PyProtectedMember
    def _set_max_window_size(self):
        """--> inform the Telnet server of the window width and height. see __negotiate_naws"""
        import struct
        from telnetlib import IAC, NAWS, SB, SE

        width = struct.pack("H", 65000)
        height = struct.pack("H", 5000)
        self._telnet.get_socket().sendall(IAC + SB + NAWS + width + height + IAC + SE)

    # noinspection PyProtectedMember
    @staticmethod
    def __negotiate_naws(tsocket, command, option):
        """--> inform the Telnet server we'll be using Window Size Option.
        Refer to https://www.ietf.org/rfc/rfc1073.txt
        :param tsocket: telnet socket object
        :param command: telnet Command
        :param option: telnet option
        :return: None
        """
        from telnetlib import DO, DONT, IAC, NAWS, WILL, WONT

        if option == NAWS:
            tsocket.sendall(IAC + WILL + NAWS)
        # -- below code taken from telnetlib
        elif command in (DO, DONT):
            tsocket.sendall(IAC + WONT + option)
        elif command in (WILL, WONT):
            tsocket.sendall(IAC + DONT + option)
