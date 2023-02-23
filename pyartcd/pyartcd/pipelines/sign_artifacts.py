import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

import click
from pyartcd.cli import cli, click_coroutine, pass_runtime
from pyartcd.runtime import Runtime
from pyartcd.signatory import Signatory


class SignArtifactsPipeline:
    """Rebase and build MicroShift for an assembly"""

    def __init__(
        self,
        runtime: Runtime,
        env: str,
        ssl_cert: Optional[str],
        ssl_key: Optional[str],
        sig_keyname: str,
        product: str,
        release_name: str,
        out_dir: Optional[str],
        json_digests: Tuple[Tuple[str, str]],
        message_digests: Tuple[Tuple[str, str]],
        logger: Optional[logging.Logger] = None,
    ):
        self.runtime = runtime
        self.env = env,
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
        self.sig_keyname = sig_keyname
        self.product = product
        self.release_name = release_name
        self.out_dir = Path(out_dir) if out_dir else self.runtime.working_dir
        self.json_digests = json_digests
        self.message_digests = message_digests
        self._logger = logger or runtime.logger

        self._signing_config = self.runtime.config.get("signing" if env == "prod" else f"signing_{env}")
        self._broker_config = self.runtime.config.get("message_broker", {}).get(self._signing_config["message_broker"])

    async def _sign_json_digest(self, signatory: Signatory, pullspec: str, digest: str):
        self._logger.info("Signing json digest for payload %s with digest %s...", pullspec, digest)
        signature_file = self.out_dir / f"{digest.replace(':', '=')}" / "signature-1"
        signature_file.parent.mkdir(parents=True, exist_ok=True)
        with open(signature_file, "wb") as sig_file:
            await signatory.sign_json_digest(self.product, self.release_name, pullspec, digest, sig_file)
        return signature_file.absolute()

    async def _sign_message_digest(self, signatory: Signatory, input_path: str, output_path: str):
        input_path = Path(input_path)
        self._logger.info("Signing message digest file %s...", input_path.absolute())
        signature_file = self.out_dir.joinpath(output_path)
        signature_file.parent.mkdir(parents=True, exist_ok=True)
        with open(input_path, "rb") as in_file, open(signature_file, "wb") as sig_file:
            await signatory.sign_message_digest(self.product, self.release_name, in_file, sig_file)
        return signature_file.absolute()

    async def run(self):
        if self.ssl_cert:
            self._broker_config["cert_file"] = self.ssl_cert
        if self.ssl_key:
            self._broker_config["key_file"] = self.ssl_key
        self._logger.info("About to sign artifacts for %s %s with key %s", self.product, self.release_name, self.sig_keyname)
        async with Signatory(self._signing_config, self._broker_config, sig_keyname=self.sig_keyname) as signatory:
            tasks = [self._sign_json_digest(signatory, pullspec, digest) for pullspec, digest in self.json_digests]
            tasks.extend((self._sign_message_digest(signatory, input_path, output_path) for input_path, output_path in self.message_digests))
            await asyncio.gather(*tasks)
        self._logger.info("All artifacts are successfully signed.")


@cli.command("sign-artifacts")
@click.option(
    "--env",
    type=click.Choice(['stage', 'prod']),
    default="stage",
    help="Which environment to sign in",
)
@click.option(
    "--ssl-cert",
    help="SSL certifiact for message broker connection",
)
@click.option(
    "--ssl-key",
    help="SSL certifiact for message broker connection",
)
@click.option(
    "--sig-keyname",
    "sig_keyname",
    metavar="KEY",
    required=True,
    help="Which key to sign with",
)
@click.option(
    "--product",
    type=click.Choice(['openshift', 'rhcos', 'coreos-installer']),
    metavar="PRODUCT",
    required=True,
    help="Product name. e.g. openshift",
)
@click.option(
    "--release",
    "release",
    metavar="RELEASE",
    required=True,
    help="Release name. e.g. 4.13.1",
)
@click.option(
    "--out-dir",
    metavar="DIR",
    help="Write signature files to the specified directory instead of working directory",
)
@click.option(
    "--json-digest",
    "json_digests",
    nargs=2,
    multiple=True,
    help="(Optional) [MULTIPLE] Pullspec and sha256 digest of the payload to sign; format is <PULLSPEC> <DIGEST>",
)
@click.option(
    "--message-digest",
    "message_digests",
    multiple=True,
    nargs=2,
    help="(Optional) [MULTIPLE] Path of the message digest file to sign; format is <INPUT_FILE> <OUTPUT_SIGNATURE_FILE>",
)
@pass_runtime
@click_coroutine
async def sign_artifacts(
    runtime: Runtime,
    env: str,
    ssl_cert: Optional[str],
    ssl_key: Optional[str],
    sig_keyname: str,
    product: str,
    release: str,
    out_dir: Optional[str],
    json_digests: Tuple[Tuple[str, str]],
    message_digests: Tuple[Tuple[str, str]],
):
    pipeline = SignArtifactsPipeline(
        runtime=runtime,
        env=env,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        sig_keyname=sig_keyname,
        product=product,
        release_name=release,
        out_dir=out_dir,
        json_digests=json_digests,
        message_digests=message_digests,
    )
    await pipeline.run()
