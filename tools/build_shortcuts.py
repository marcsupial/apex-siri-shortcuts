#!/usr/bin/env python3
"""Build signed Siri Shortcuts that control a Neptune Apex the way its web dashboard does.

Each shortcut replays the HTTP requests the Apex's local dashboard (http://<apex>/) makes
when you press one of its buttons. docs/apex-local-api.md describes those requests.

    python3 tools/build_shortcuts.py                        # signed shortcuts in shortcuts/
    python3 tools/build_shortcuts.py --mock 127.0.0.1:8737  # plus build/Apex Mock Test.shortcut
    python3 tools/build_shortcuts.py --no-sign              # readable XML plists in build/
"""
from __future__ import annotations

import argparse
import plistlib
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTCUTS = ROOT / "shortcuts"  # signed and ready to import; committed
BUILD = ROOT / "build"          # mock-test shortcut and review plists; not committed
PROJECT_URL = "https://github.com/marcsupial/apex-siri-shortcuts"

# The plist format here was checked against shortcuts Apple ships with Shortcuts 10.0.
# Shortcuts upgrades files written by older versions on import, so this stays pinned to
# the version the format was written for, not whatever is installed.
CLIENT_VERSION = "5037.0.19"

# The dashboard's FEED CYCLE tile sends name 1-4 for buttons A-D, and 0 for CANCEL.
FEED_CYCLES = {"A": 1, "B": 2, "C": 3, "D": 4}

MOCK_LOGIN = ("admin", "mock-password")  # mock_apex.py's defaults

# Inside a text field, Shortcuts marks where a variable sits with U+FFFC (OBJECT REPLACEMENT CHARACTER).
VARIABLE_MARKER = chr(0xFFFC)

# If action conditions (WFCondition).
IS = 4
HAS_ANY_VALUE = 100


def new_uuid() -> str:
    return str(uuid.uuid4()).upper()


@dataclass(frozen=True)
class Var:
    """An earlier action's output, used as a variable."""

    uuid: str
    name: str

    def attachment(self, as_text: bool = False) -> dict:
        value = {"OutputName": self.name, "OutputUUID": self.uuid, "Type": "ActionOutput"}
        if as_text:
            value["Aggrandizements"] = [
                {"Type": "WFCoercionVariableAggrandizement", "CoercionItemClass": "WFStringContentItem"}
            ]
        return value


def text(*parts: str | Var) -> dict:
    """A text field mixing literal strings and variables (WFTextTokenString)."""
    string, attachments = "", {}
    for part in parts:
        if isinstance(part, Var):
            # Ranges count UTF-16 code units, like NSString.
            attachments[f"{{{len(string.encode('utf-16-le')) // 2}, 1}}"] = part.attachment()
            string += VARIABLE_MARKER
        else:
            string += part
    value = {"string": string}
    if attachments:
        value["attachmentsByRange"] = attachments
    return {"Value": value, "WFSerializationType": "WFTextTokenString"}


def variable(var: Var, as_text: bool = False) -> dict:
    """A parameter that takes one whole variable (WFTextTokenAttachment)."""
    return {"Value": var.attachment(as_text), "WFSerializationType": "WFTextTokenAttachment"}


def dictionary(fields: dict) -> dict:
    """Key/value rows for a JSON body or headers (WFDictionaryFieldValue).

    The Python type picks the JSON type: bool -> true/false, int -> number,
    and str, Var, or a tuple of them -> string.
    """
    items = []
    for key, value in fields.items():
        if isinstance(value, bool):  # before int: bool is an int subclass
            item_type, wf_value = 4, {"Value": value, "WFSerializationType": "WFNumberSubstitutableState"}
        elif isinstance(value, int):
            item_type, wf_value = 3, text(str(value))
        else:
            item_type, wf_value = 0, text(*(value if isinstance(value, tuple) else (value,)))
        items.append({"WFItemType": item_type, "WFKey": text(key), "WFValue": wf_value})
    return {"Value": {"WFDictionaryFieldValueItems": items}, "WFSerializationType": "WFDictionaryFieldValue"}


class Shortcut:
    """Collects actions and import questions, then serializes to the .shortcut plist."""

    def __init__(self, name: str, ask_on_import: bool = True):
        self.name = name
        self.ask_on_import = ask_on_import
        self.actions: list[dict] = []
        self.import_questions: list[dict] = []

    def add(self, identifier: str, output: str | None = None, **params) -> Var | None:
        """Append an action. Naming its output makes it usable as a variable later."""
        var = None
        if output:
            var = Var(new_uuid(), output)
            params |= {"UUID": var.uuid, "CustomOutputName": output}
        self.actions.append({"WFWorkflowActionIdentifier": identifier, "WFWorkflowActionParameters": params})
        return var

    def comment(self, note: str) -> None:
        self.add("is.workflow.actions.comment", WFCommentActionText=note)

    def setting(self, name: str, value: str, question: str) -> Var:
        """A Text action holding a per-person value, asked for when the file is imported."""
        if self.ask_on_import:
            self.import_questions.append({
                "ActionIndex": len(self.actions),
                "Category": "Parameter",
                "DefaultValue": value,
                "ParameterKey": "WFTextActionText",
                "Text": question,
            })
        return self.add("is.workflow.actions.gettext", name, WFTextActionText=text(value))

    def trimmed(self, source: Var, output: str) -> Var:
        """source without leading or trailing whitespace (Replace Text with a regex)."""
        return self.add("is.workflow.actions.text.replace", output, WFInput=text(source),
                        WFReplaceTextFind=r"^\s+|\s+$", WFReplaceTextReplace="",
                        WFReplaceTextRegularExpression=True)

    def request(self, method: str, url: dict, output: str | None = None, *,
                headers: dict | None = None, json: dict | None = None) -> Var | None:
        """Get Contents of URL."""
        params = {"WFURL": url, "WFHTTPMethod": method}
        if headers:
            params |= {"ShowHeaders": True, "WFHTTPHeaders": dictionary(headers)}
        if json is not None:
            params |= {"WFHTTPBodyType": "JSON", "WFJSONValues": dictionary(json)}
        return self.add("is.workflow.actions.downloadurl", output, **params)

    def first_group(self, source: Var, pattern: str, output: str) -> Var:
        """Capture group 1 of a regex match in source (Match Text, then Get Group)."""
        matches = self.add("is.workflow.actions.text.match", f"{output} Match",
                           text=text(source), WFMatchTextPattern=pattern, WFMatchTextCaseSensitive=True)
        return self.add("is.workflow.actions.text.match.getgroup", output,
                        matches=variable(matches), WFGetGroupType="Group At Index", WFGroupIndex=1)

    def dig(self, source: Var, keys: list[str], output: str) -> Var:
        """A nested dictionary value, looked up with one Get Dictionary Value per key."""
        for i, key in enumerate(keys):
            name = output if i == len(keys) - 1 else key
            source = self.add("is.workflow.actions.getvalueforkey", name,
                              WFInput=variable(source), WFDictionaryKey=key)
        return source

    def wait(self, seconds: int) -> None:
        self.add("is.workflow.actions.delay", WFDelayTime=seconds)

    def show(self, message: str) -> None:
        """Show Result. Siri speaks it when the shortcut runs by voice."""
        self.add("is.workflow.actions.showresult", Text=text(message))

    def if_(self, subject: Var, condition: int, value: str | None = None) -> str:
        """Open an If block testing subject, as text. Returns the block id."""
        block = new_uuid()
        params = {"GroupingIdentifier": block, "WFControlFlowMode": 0, "WFCondition": condition,
                  "WFInput": {"Type": "Variable", "Variable": variable(subject, as_text=True)}}
        if value is not None:
            params["WFConditionalActionString"] = value
        self.add("is.workflow.actions.conditional", **params)
        return block

    def otherwise(self, block: str) -> None:
        self.add("is.workflow.actions.conditional", GroupingIdentifier=block, WFControlFlowMode=1)

    def end_if(self, block: str) -> None:
        self.add("is.workflow.actions.conditional", GroupingIdentifier=block, WFControlFlowMode=2,
                 UUID=new_uuid())

    def to_plist(self) -> dict:
        return {
            "WFWorkflowActions": self.actions,
            "WFWorkflowImportQuestions": self.import_questions,
            "WFWorkflowClientVersion": CLIENT_VERSION,
            "WFWorkflowMinimumClientVersion": 900,
            "WFWorkflowMinimumClientVersionString": "900",
            "WFWorkflowIcon": {"WFWorkflowIconStartColor": 463140863, "WFWorkflowIconGlyphNumber": 59511},
            "WFWorkflowInputContentItemClasses": [],
            "WFWorkflowOutputContentItemClasses": [],
            "WFWorkflowHasOutputFallback": False,
            "WFWorkflowHasShortcutInputVariables": False,
            "WFQuickActionSurfaces": [],
            "WFWorkflowTypes": [],
        }


def feed_shortcut(cycle: str, address: str, name: str | None = None,
                  login: tuple[str, str] | None = None) -> Shortcut:
    """Press the dashboard's Feed <cycle> button, then confirm the Apex reports it running.

    Without `login`, Shortcuts asks for the address, username, and password when the
    file is imported, so credentials live only in your shortcut library.
    """
    feed_id = FEED_CYCLES[cycle]
    s = Shortcut(name or f"Feed Mode {cycle}", ask_on_import=login is None)
    username, password = login or ("admin", "")
    s.comment(f"Starts Feed Cycle {cycle} on a Neptune Apex by sending the same requests as the "
              f"Feed {cycle} button in the Apex's web dashboard. Source and updates: {PROJECT_URL}")
    # The dashboard trims what you type into its login form, so a stray space doesn't matter there.
    host = s.trimmed(s.setting("Apex Address", address,
                               "Your Apex's address: what you type in a browser to open its dashboard, "
                               "such as 192.168.1.50 or apex.local"), "Address")
    user = s.trimmed(s.setting("Apex Username", username,
                               "Your Apex username (the one you sign in to the dashboard with)"), "Username")
    pw = s.trimmed(s.setting("Apex Password", password, "Your Apex password"), "Password")

    login_response = s.request("POST", text("http://", host, "/rest/login"), "Login Response",
                               json={"login": user, "password": pw, "remember_me": False})
    # The session id also comes back in the login body. Sending it ourselves doesn't rely on
    # Shortcuts keeping cookies between requests. A regex, because Get Dictionary Value may
    # read the dot in "connect.sid" as a nested key path.
    session = s.first_group(login_response, r'"connect\.sid"\s*:\s*"([^"]+)"', "Session ID")
    # Get Contents of URL doesn't stop on HTTP errors, so a rejected login (a 401 page with no
    # session id) has to be caught here, or it would look like the feed failing to start.
    signed_in = s.if_(session, HAS_ANY_VALUE)
    s.request("PUT", text("http://", host, f"/rest/status/feed/{feed_id}"),
              headers={"Cookie": ("connect.sid=", session)},
              json={"name": feed_id, "active": 1})

    # Ask the Apex whether the feed is really running. It applies the change on its next tick,
    # so give it a moment first.
    s.wait(2)
    status = s.request("GET", text("http://", host, "/cgi-bin/status.json"), "Apex Status")
    running = s.dig(status, ["istat", "feed", "name"], "Running Feed")
    started = s.if_(running, IS, str(feed_id))
    s.show(f"Feed {cycle} is running.")
    s.otherwise(started)
    s.show(f"The Apex accepted the login, but Feed {cycle} didn't start.")
    s.end_if(started)
    s.otherwise(signed_in)
    s.show("The Apex rejected the username or password saved in this shortcut.")
    s.end_if(signed_in)
    return s


def sign(shortcut: Shortcut, destination: Path) -> None:
    """Shortcuts only imports signed files. "anyone" mode imports on any device."""
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = Path(tmp) / f"{shortcut.name}.shortcut"
        unsigned.write_bytes(plistlib.dumps(shortcut.to_plist(), fmt=plistlib.FMT_BINARY))
        subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", unsigned, "--output", destination],
                       check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Siri Shortcuts for a Neptune Apex.")
    parser.add_argument("--address", default="",
                        help="Apex address to prefill when importing (default: none, so people enter their own)")
    parser.add_argument("--mock", metavar="HOST:PORT",
                        help="also build 'Apex Mock Test', the Feed A shortcut aimed at mock_apex.py")
    parser.add_argument("--no-sign", action="store_true",
                        help="write readable XML plists to build/ instead of signed, importable files")
    args = parser.parse_args()

    builds = [(SHORTCUTS, feed_shortcut("A", args.address))]
    if args.mock:
        # Padded on purpose: the mock only accepts the exact login, so a run that succeeds
        # proves the shortcut trims like the dashboard.
        username, password = (f" {value} " for value in MOCK_LOGIN)
        builds.append((BUILD, feed_shortcut("A", f" {args.mock} ", name="Apex Mock Test",
                                            login=(username, password))))

    for folder, shortcut in builds:
        if args.no_sign:
            BUILD.mkdir(exist_ok=True)
            path = BUILD / f"{shortcut.name}.plist"
            path.write_bytes(plistlib.dumps(shortcut.to_plist(), fmt=plistlib.FMT_XML))
        else:
            folder.mkdir(exist_ok=True)
            path = folder / f"{shortcut.name}.shortcut"
            sign(shortcut, path)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
