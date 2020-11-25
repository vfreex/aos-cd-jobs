import argparse
import logging
import os
import re
import shutil
import smtplib
import subprocess
from datetime import datetime
from email.generator import Generator
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

import toml
import jinja2

from pyartcd.jira import JIRAClient

_LOGGER = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class PrepareReleasePipeline:
    def __init__(
        self,
        name: str,
        date: str,
        nightlies: List[str],
        package_owner: str,
        config: Dict,
        working_dir: str,
        dry_run=False,
    ) -> None:
        self.config = config
        self.release_name = name
        self.release_date = date
        self.candidate_nightlies = {}
        for nightly in nightlies:
            if "s390x" in nightly:
                arch = "s390x"
            elif "ppc64le" in nightly:
                arch = "ppc64le"
            else:
                arch = "x86_64"
            if ":" not in nightly:
                # prepend pullsepc URL to nightly name
                arch_suffix = "" if arch == "x86_64" else "-" + arch
                nightly = f"registry.svc.ci.openshift.org/ocp{arch_suffix}/release{arch_suffix}:{nightly}"
            self.candidate_nightlies[arch] = nightly
        self.package_owner = package_owner or self.config["advisory"]["package_owner"]
        self.working_dir = Path(working_dir)
        self.dry_run = dry_run
        self.release_version = tuple(map(int, self.release_name.split(".", 2)))
        self.group_name = (
            f"openshift-{self.release_version[0]}.{self.release_version[1]}"
        )
        self.elliott_working_dir = self.working_dir / "elliott-working"

        self.jira_username = os.environ.get("JIRA_USERNAME")
        if not self.jira_username:
            raise ValueError("JIRA_USERNAME environment variable is not set")
        self.jira_password = os.environ.get("JIRA_PASSWORD")
        if not self.jira_password:
            raise ValueError("JIRA_PASSWORD environment variable is not set")

    def run(self):
        _LOGGER.info("Initializing and verifying parameters...")
        self.working_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Creating advisories for release %s...",
                     self.release_name)
        advisories = {}
        # if self.release_version[2] == 0:  # GA release
        #     advisories["rpm"] = self.create_advisory("RHEA", "rpm", "ga")
        #     advisories["image"] = self.create_advisory("RHEA", "image", "ga")
        # else:  # z-stream release
        #     advisories["rpm"] = self.create_advisory("RHBA", "rpm", "standard")
        #     advisories["image"] = self.create_advisory(
        #         "RHBA", "image", "standard")
        # if self.release_version[0] > 3:
        #     advisories["extras"] = self.create_advisory(
        #         "RHBA", "image", "extras")
        #     advisories["metadata"] = self.create_advisory(
        #         "RHBA", "image", "metadata")
        # _LOGGER.info("Created advisories: %s", advisories)

        # _LOGGER.info("Saving the advisories to ocp-build-data...")
        # self.save_advisories(advisories)

        advisories = {'rpm': 66623, 'image': 66624,
                      'extras': 66625, 'metadata': 66626}

        _LOGGER.info("Sweep bugs into the the advisories...")
        self.sweep_bugs()

        _LOGGER.info("Adding placeholder bugs to the advisories...")
        for kind, advisory in advisories.items():
            # don't create placeholder bugs for OCP 4 image advisory and OCP 3 rpm advisory
            if (
                not advisory
                or self.release_version[0] >= 4
                and kind == "image"
                or self.release_version[0] < 4
                and kind == "rpm"
            ):
                continue
            self.create_and_attach_placeholder_bug(kind, advisory)

        _LOGGER.info("Sweep builds into the the advisories...")
        for kind, advisory in advisories.items():
            if not advisory:
                continue
            self.change_advisory_state(advisory, "NEW_FILES")
            if kind == "rpm":
                self.sweep_builds("rpm", advisory)
            elif kind == "image":
                self.sweep_builds(
                    "image", advisory, only_payload=self.release_version[0] >= 4
                )
            elif kind == "extras":
                self.sweep_builds("image", advisory, only_non_payload=True)

        if self.release_version[0] < 4:
            _LOGGER.info("Don't verify payloads for OCP3 releases")
        elif not self.candidate_nightlies:
            _LOGGER.warn(
                "Don't verify payloads because candidate nightlies are not given"
            )
        else:
            _LOGGER.info("Verify the swept builds match the nightlies...")
            for _, payload in self.candidate_nightlies.items():
                self.verify_payload(payload, advisories["image"])

        _LOGGER.info("Creating a release JIRA...")
        self.create_release_jira(advisories)

        _LOGGER.info("Sending an Errata live ID request email...")
        self.send_live_id_request_mail(advisories)

    def create_advisory(self, type: str, kind: str, impetus: str) -> int:
        create_cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "create",
            f"--type={type}",
            f"--kind={kind}",
            f"--impetus={impetus}",
            f"--assigned-to={self.config['advisory']['assigned_to']}",
            f"--manager={self.config['advisory']['manager']}",
            f"--package-owner={self.package_owner}",
            f"--date={self.release_date}",
        ]
        if not self.dry_run:
            create_cmd.append("--yes")
        _LOGGER.debug("Running command: %s", create_cmd)
        result = subprocess.run(create_cmd, check=False,
                                capture_output=True, universal_newlines=True)
        if result.returncode != 0:
            raise IOError(
                f"Command {create_cmd} returned {result.returncode}: stdout={result.stdout}, stderr={result.stderr}"
            )
        match = re.search(
            r"https:\/\/errata\.devel\.redhat\.com\/advisory\/([0-9]+)", result.stdout
        )
        advisory_num = int(match[1])
        return advisory_num

    def save_advisories(self, advisories: Dict[str, int]):
        if not advisories:
            return
        repo = self.working_dir / "ocp-build-data-push"
        shutil.rmtree(repo, ignore_errors=True)
        # shallow clone ocp-build-data
        cmd = [
            "git",
            "-C",
            self.working_dir,
            "clone",
            "-b",
            self.group_name,
            "--depth=1",
            self.config["build_config"]["ocp_build_data_repo_push_url"],
            "ocp-build-data-push",
        ]
        _LOGGER.debug("Running command: %s", cmd)
        subprocess.run(cmd, check=True, universal_newlines=True)
        # update advisory numbers
        with open(repo / "group.yml", "r") as f:
            group_config = f.read()
            # yaml = YAML(typ="rt")
            # group_config = yaml.load(f)
        for kind, advisory in advisories.items():
            new_group_config = re.sub(
                fr"^(\s+{kind}:)\s*[0-9]+$", fr"\1 {advisory}", group_config, count=1, flags=re.MULTILINE
            )
            group_config = new_group_config
        with open(repo / "group.yml", "w") as f:
            f.write(group_config)
        cmd = ["git", "-C", repo, "add", "."]
        subprocess.run(cmd, check=True, universal_newlines=True)
        cmd = ["git", "-C", repo, "commit", "-m",
               "Update advisories on group.yml"]
        subprocess.run(cmd, check=True, universal_newlines=True)
        if not self.dry_run:
            _LOGGER.info("Pushing changes to upstream...")
            cmd = ["git", "-C", repo, "push", "origin", self.group_name]
            subprocess.run(cmd, check=True, universal_newlines=True)
        else:
            _LOGGER.warn("Would have run %s", cmd)
            _LOGGER.warn("Would have pushed changes to upstream")

    def create_and_attach_placeholder_bug(self, kind: str, advisory: int):
        cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "create-placeholder",
            f"--kind={kind}",
            f"--attach={advisory}",
        ]
        _LOGGER.debug("Running command: %s", cmd)
        if self.dry_run:
            _LOGGER.warn("Would have run: %s", cmd)
        else:
            subprocess.run(cmd, check=True, universal_newlines=True)

    def sweep_bugs(
        self,
        statuses: List[str] = ["ON_QA", "VERIFIED"],
        include_cve: bool = True,
        advisory: Optional[int] = None,
    ):
        cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "find-bugs",
            "--mode=sweep",
        ]
        if include_cve:
            cmd.append("--cve-trackers")
        for status in statuses:
            cmd.append("--status=" + status)
        if advisory:
            cmd.append(f"--add={advisory}")
        else:
            cmd.append("--into-default-advisories")
        if self.dry_run:
            cmd.append("--dry-run")
        _LOGGER.debug("Running command: %s", cmd)
        subprocess.run(cmd, check=True, universal_newlines=True)

    def sweep_builds(
        self, kind: str, advisory: int, only_payload=False, only_non_payload=False
    ):
        cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "find-builds",
            f"--kind={kind}",
        ]
        if only_payload:
            cmd.append("--payload")
        if only_non_payload:
            cmd.append("--non-payload")
        if not self.dry_run:
            cmd.append(f"--attach={advisory}")
        _LOGGER.debug("Running command: %s", cmd)
        subprocess.run(cmd, check=True, universal_newlines=True)

    def change_advisory_state(self, advisory: int, state: str):
        cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "change-state",
            "-s",
            state,
            "-a",
            str(advisory),
        ]
        if self.dry_run:
            cmd.append("--dry-run")
        _LOGGER.debug("Running command: %s", cmd)
        subprocess.run(cmd, check=True, universal_newlines=True)
        _LOGGER.info("Moved advisory %d to %s", advisory, state)

    def verify_payload(self, pullspec, advisory):
        cmd = [
            "elliott",
            f"--working-dir={self.elliott_working_dir}",
            f"--group={self.group_name}",
            "verify-payload",
            f"{pullspec}",
            f"{advisory}",
        ]
        _LOGGER.debug("Running command: %s", cmd)
        subprocess.run(cmd, check=True, universal_newlines=True)

    def create_release_jira(self, advisories: Dict[str, Any]):
        template_issue_key = self.config["jira"]["templates"][f"ocp{self.release_version[0]}"]

        _LOGGER.info("Creating release JIRA from template %s...",
                     template_issue_key)
        jira_client = JIRAClient.from_url(
            self.config["jira"]["url"], basic_auth=(self.jira_username, self.jira_password))
        template_issue = jira_client.get_issue(template_issue_key)

        def fields_transform(fields):
            labels = set(fields.get("labels", []))
            if "template" not in labels:
                return fields  # no need to modify fields of subtasks
            # remove "template" label
            fields["labels"] = list(labels - {"template"})
            if fields.get("summary"):
                fields["summary"] = f"TEST - Release {self.release_name} [{self.release_date}]"
            if fields.get("description"):
                template = jinja2.Template(fields["description"])
                fields["description"] = template.render(
                    advisories=advisories,
                    release_date=self.release_date,
                    candiate_nightlies=self.candidate_nightlies,
                ).strip()
            return fields
        if self.dry_run:
            fields = fields_transform(template_issue.raw["fields"].copy())
            _LOGGER.info(
                "Would have created release JIRA with fields: %s", fields)
        else:
            new_issues = jira_client.clone_issue_with_subtasks(
                template_issue, fields_transform=fields_transform)
            _LOGGER.info("Created release JIRA: %s", new_issues[0].permalink())

    def send_live_id_request_mail(self, advisories: Dict[str, int]):
        subject = f"Live IDs for {self.release_name}"
        main_advisory = "image" if self.release_version[0] >= 4 else "rpm"
        content = f"""Hello docs team,

ART would like to request Live IDs for our {self.release_name} advisories:
{main_advisory}: https://errata.devel.redhat.com/advisory/{advisories[main_advisory]}

This is the current set of advisories we intend to ship:
"""
        for kind, advisory in advisories.items():
            content += (
                f"- {kind}: https://errata.devel.redhat.com/advisory/{advisory}\n"
            )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config["email"]["from"]
        msg["To"] = (
            "yuxzhu@redhat.com" or self.config["email"]["live_id_request_recipients"]
        )
        cc = self.config["email"].get("cc")
        if cc:
            msg["CC"] = cc
        reply_to = self.config["email"].get("reply_to")
        if reply_to:
            msg["Reply-to"] = reply_to
        msg.set_content(content)

        _LOGGER.info("Saving email to file...")
        os.makedirs("email", exist_ok=True)
        filename = (
            "email-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-"
            + re.sub(r"[^@.\w]+", "_", msg["To"])
            + re.sub(r"[^@.\w]+", "_", subject)
            + ".eml"
        )
        with open(Path("email") / filename, "w") as f:
            gen = Generator(f)
            gen.flatten(msg)

        _LOGGER.debug("Sending email to %s: %s - %s",
                      msg["To"], subject, content)

        if self.dry_run:
            smtp = smtplib.SMTP(self.config["email"]["smtp_server"])
            smtp.send_message(msg)
            smtp.quit()
        else:
            _LOGGER.warn("Would have sent email: %s", msg)


def main():
    parser = argparse.ArgumentParser("prepare-release")
    parser.add_argument("name", help="release name (e.g. 4.6.42)")
    parser.add_argument(
        "--date", required=True, help="expected release date (e.g. 2020-11-25)"
    )
    parser.add_argument(
        "--nightly",
        dest="nightlies",
        action="append",
        help="candidate nightly",
    )
    parser.add_argument(
        "--package-owner",
        default="lmeyer@redhat.com",
        help="Must be an individual email address; may be anyone who wants random advisory spam",
    )
    parser.add_argument("-c", "--config", required=True,
                        help="configuration file")
    parser.add_argument(
        "-C", "--working-dir", default=".", help="set working directory"
    )
    parser.add_argument(
        "-v", "--verbosity", action="count", help="[MULTIPLE] increase output verbosity"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't actually prepare a new release; just print what would be done",
    )
    args = parser.parse_args()
    if not args.verbosity:
        logging.basicConfig(level=logging.WARNING)
    elif args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbosity >= 2:
        logging.basicConfig(level=logging.DEBUG)

    with open(args.config, "r") as config_file:
        config = toml.load(config_file)
    pipeline = PrepareReleasePipeline(
        args.name,
        args.date,
        args.nightlies,
        args.package_owner,
        config,
        args.working_dir,
        dry_run=args.dry_run,
    )
    pipeline.run()
    return 0


if __name__ == "__main__":
    exit(main())
