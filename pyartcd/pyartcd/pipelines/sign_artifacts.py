import asyncio
import logging
import os
import re
import traceback
from collections import namedtuple
from io import StringIO
from typing import Iterable, Optional, OrderedDict, Tuple
import uuid

import click
from pyartcd import exectools, constants
from pyartcd.cli import cli, click_coroutine, pass_runtime
from pyartcd.runtime import Runtime
from pyartcd.signatory import Signatory
from ruamel.yaml import YAML

yaml = YAML(typ="rt")
yaml.preserve_quotes = True


class GenAssemblyPipeline:
    """ Rebase and build MicroShift for an assembly """

    def __init__(self, runtime: Runtime, group: str, assembly: str, ocp_build_data_url: str,
                 nightlies: Tuple[str, ...], logger: Optional[logging.Logger] = None):
        self.runtime = runtime
        self.group = group
        self.assembly = assembly
        self.nightlies = nightlies
        self._logger = logger or runtime.logger
        self._slack_client = self.runtime.new_slack_client()
        self._working_dir = self.runtime.working_dir.absolute()

        # self._github_token = os.environ.get('GITHUB_TOKEN')
        # if not self._github_token and not self.runtime.dry_run:
        #     raise ValueError("GITHUB_TOKEN environment variable is required to create a pull request.")

        # determines OCP version
        match = re.fullmatch(r"openshift-(\d+).(\d+)", group)
        if not match:
            raise ValueError(f"Invalid group name: {group}")
        self._ocp_version = (int(match[1]), int(match[2]))

        # sets environment variables for Doozer
        self._doozer_env_vars = os.environ.copy()
        self._doozer_env_vars["DOOZER_WORKING_DIR"] = str(self._working_dir / "doozer-working")

        if not ocp_build_data_url:
            ocp_build_data_url = self.runtime.config.get("build_config", {}).get("ocp_build_data_url")
        if ocp_build_data_url:
            self._doozer_env_vars["DOOZER_DATA_PATH"] = ocp_build_data_url

    async def run(self):
        self._logger.info("Build started")
        # import stomp

        # class MyListener(stomp.ConnectionListener):
        #     def on_error(self, frame):
        #         print('received an error "%s"' % frame.body)

        #     def on_message(self, frame):
        #         print('received a message "%s"' % frame.body)
        # stomp_config = {
        #     'host_and_ports': [
        #         ('umb-broker03.stage.api.redhat.com', 61612),
        #         ('umb-broker04.stage.api.redhat.com', 61612),
        #     ],
        # }
        # conn = stomp.Connection12(**stomp_config)
        # conn.set_ssl(
        #     for_hosts=[
        #         ('umb-broker03.stage.api.redhat.com', 61612),
        #         ('umb-broker04.stage.api.redhat.com', 61612),
        #     ],
        #     cert_file="ssl/nonprod-openshift-art-bot.crt",
        #     key_file="ssl/nonprod-openshift-art-bot.key",
        # )
        # # conn.set_listener('', MyListener())
        # conn.set_listener('', stomp.PrintingListener())
        # conn.connect(wait=True, headers={
        #     'receipt': str(uuid.uuid4())
        # })
        # #conn.subscribe(destination='/queue/Consumer.nonprod-openshift-art-bot.stage.VirtualTopic.eng.robosignatory.art.sign', id=1, ack='auto')
        # # conn.subscribe(destination='/queue/Consumer.nonprod-openshift-art-bot.stage.VirtualTopic.eng.art.artifact.sign', id=1, ack='auto')
        # receipt = str(uuid.uuid4())
        # conn.send(body='test', destination='/topic/VirtualTopic.eng.art.artifact.sign', headers={
        #     'receipt': receipt
        # })
        # await asyncio.sleep(20)
        # conn.disconnect()

        signatory = Signatory(None)
        await signatory.connect()
        await signatory.subscribe()
        # await signotory.request_signing("testtest")
        await signatory.sign_ocp_payload('4.11.0-0.nightly-multi-2023-02-21-004457', 'sha256:70a26408942f5ecabd29e98933ed0bf715aa72b4b21974d1ecbf1eac31f82702')
        artifact_raw = """
ba0c33e239e7e9c027f0f8ba112d2853adc56f949947e5295577c78f106df95e  amd64/sha256sum.txt
e05021afcc0ef02d0376df83e5d8b561520a8e3ece406371df6106db5871760a  arm64/sha256sum.txt
50e6c63f2e1f7e84a80db0dc477d1ffaadc133a2eef52c7c4c79c7d969bf91b5  ppc64le/sha256sum.txt
34ec90d2adb0af86db9628ee98e006851330b1b29c9ffe76908352b6cc560816  s390x/sha256sum.txt
        """.strip()
        # await signatory.sign_message_digest('4.11.0-0.nightly-multi-2023-02-21-004457', artifact_raw)
        # await signatory.disconnect()
        pass


@cli.command("sign-artifacts")
@click.option("--data-path", metavar='BUILD_DATA', default=None,
              help=f"Git repo or directory containing groups metadata e.g. {constants.OCP_BUILD_DATA_URL}")
@click.option("-g", "--group", metavar='NAME', required=True,
              help="The group of components on which to operate. e.g. openshift-4.9")
@click.option("--assembly", metavar="ASSEMBLY_NAME", required=True,
              help="The name of an assembly to generate for. e.g. 4.9.1")
@click.option("--nightly", "nightlies", metavar="TAG", multiple=True,
              help="(Optional) [MULTIPLE] List of nightlies to match with `doozer get-nightlies` (if empty, find latest)")
@pass_runtime
@click_coroutine
async def sign_artifacts(runtime: Runtime, data_path: str, group: str, assembly: str, nightlies: Tuple[str, ...]):
    pipeline = GenAssemblyPipeline(runtime=runtime, group=group, assembly=assembly, ocp_build_data_url=data_path,
                                   nightlies=nightlies)
    await pipeline.run()
