import asyncio
import base64
import io
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, BinaryIO, Dict, Tuple, cast

import stomp

_LOGGER = logging.getLogger(__name__)


class _Listener(stomp.ConnectionListener):
    def __init__(self, signatory: "Signatory", print_to_log=True):
        self._signatory = signatory
        self.print_to_log = print_to_log
        self._futures: Dict[str, asyncio.Future] = {}

    def __print(self, msg, *args):
        if self.print_to_log:
            logging.debug(msg, *args)
        else:
            print(msg % args)

    def add_future(self, id: str, fut: asyncio.Future):
        if id in self._futures:
            if not self._futures[id].done():
                self._futures[id].cancel()
        self._futures[id] = fut

    def remove_future(self, id: str):
        if id in self._futures:
            if not self._futures[id].done():
                self._futures[id].cancel()
        del self._futures[id]

    def _future_complete(self, id: str, result: Any):
        fut = self._futures.get(id)
        if not fut:
            return
        fut.get_loop().call_soon_threadsafe(fut.set_result, result)

    def _future_exception(self, id: str, message: str):
        fut = self._futures.get(id)
        if not fut:
            return
        fut.get_loop().call_soon_threadsafe(fut.set_exception, IOError(message))

    def on_connecting(self, host_and_port):
        """
        :param (str,int) host_and_port:
        """
        self.__print("on_connecting %s %s", *host_and_port)

    def on_connected(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_connected %s %s", frame.headers, frame.body)
        # receipt = frame.headers.get('receipt-id')
        # if receipt:
        #     self._future_complete(receipt, None)
        self._future_complete("connect", None)

    def on_disconnected(self):
        self.__print("on_disconnected")
        self._future_exception("connect", "Connection interrupted.")

    def on_heartbeat_timeout(self):
        self.__print("on_heartbeat_timeout")

    def on_before_message(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_before_message %s %s", frame.headers, frame.body)

    def on_message(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        # self.__print("on_message %s %s", frame.headers, frame.body)
        message_id = frame.headers["message-id"]
        loop = self._signatory._loop
        loop.call_soon_threadsafe(self._on_signatory_response, message_id, frame)
        # loop.call_soon_threadsafe(self._queue.put_nowait, (frame.headers, frame.body))

    def _on_signatory_response(self, message_id, frame):
        timestamp = int(frame.headers.get("timestamp", "0")) / 1000
        if datetime.utcnow() - datetime.utcfromtimestamp(timestamp) >= timedelta(
            hours=2
        ):
            _LOGGER.warning("Discard stale message {}".format(request_id))
            self._signatory._conn.ack(message_id, 1)  # discard the message
            return
        request_id = None
        try:
            body = json.loads(frame.body)
        except json.JSONDecodeError:
            _LOGGER.warning("Unable to parse message: %s", message_id)
        msg = body["msg"]
        if not isinstance(msg, dict):
            _LOGGER.warning(
                "Message %s contains content of invalid type %s", message_id, type(msg)
            )
        else:
            request_id = msg.get("request_id")
        if not request_id:
            _LOGGER.warning("No request_id in message %s", message_id)
            self._signatory._conn.ack(message_id, 1)  # discard the message
            return
        fut = self._futures.get(request_id)
        if fut:
            fut.set_result((message_id, frame.headers, msg))
            del self._futures[request_id]
        else:
            self._signatory._conn.nack(message_id, 1)

    def on_receipt(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_receipt %s %s", frame.headers, frame.body)
        receipt = frame.headers.get("receipt-id")
        if receipt:
            self._future_complete(receipt, frame.body)

    def on_error(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_error %s %s", frame.headers, frame.body)
        receipt = frame.headers.get("receipt-id")
        if receipt:
            self._future_exception(receipt, frame.headers.get("message"))

    def on_send(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_send %s %s %s", frame.cmd, frame.headers, frame.body)

    def on_heartbeat(self):
        self.__print("on_heartbeat")


class Signatory:
    @classmethod
    def _create_connection(cls, broker_config: dict):
        host_and_ports = list(map(tuple, broker_config["host_and_ports"]))
        conn = stomp.Connection11(host_and_ports=host_and_ports)
        conn.set_ssl(
            for_hosts=host_and_ports,
            cert_file=broker_config["cert_file"],
            key_file=broker_config["key_file"],
        )
        return conn

    def __init__(
        self,
        signing_config: dict,
        broker_config: dict,
        sig_keyname="test",
        requestor="timer",
    ) -> None:
        self._loop = asyncio.get_event_loop()
        self._conn = self._create_connection(broker_config)
        self._listener = _Listener(self)
        self._conn.set_listener("", self._listener)
        self._subscribed = False
        self._send_destination = signing_config["send_destination"]
        self._consumer = signing_config["recv_destination"]
        self.sig_keyname = sig_keyname
        self.requestor = requestor

    async def subscribe(self):
        """ Subscribe to the queue or topic that is specified in the config
        """
        self._conn.subscribe(destination=self._consumer, id=1, ack="client-individual")
        self._subscribed = True

    async def unsubscribe(self):
        """ Unsubscribe from the queue or topic
        """
        self._conn.unsubscribe(id=1)
        self._subscribed = False

    async def connect(self):
        """ Connect to the message broker
        """
        receipt = str(uuid.uuid4())
        _LOGGER.info("Connecting to message bus...")
        fut = self._loop.create_future()
        self._listener.add_future("connect", fut)
        self._conn.connect(wait=False, headers={"receipt": receipt})
        try:
            await fut
        finally:
            self._listener.remove_future("connect")

    async def disconnect(self):
        """ Disconnect from the message broker
        """
        receipt = str(uuid.uuid4())
        _LOGGER.info("Disconnecting from message bus...")
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.disconnect(receipt=receipt)
        try:
            await fut
        finally:
            self._listener.remove_future(receipt)

    async def __aenter__(self):
        await self.connect()
        await self.subscribe()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.unsubscribe()
        await self.disconnect()

    async def _ack_message(self, message_id: str):
        """ Acknowledge 'consumption' of a message by id.
        """
        receipt = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.ack(message_id, 1, receipt=receipt)
        await fut

    async def _nack_message(self, message_id: str):
        """ Notify the message broker that a message was not consumed.
        """
        receipt = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.nack(message_id, 1, receipt=receipt)
        await fut

    async def _send_request(self, request: Any):
        """ Send a message to the broker and wait for the receipt
        """
        receipt = str(uuid.uuid4())
        _LOGGER.debug("Sending message...")
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.send(
            body=request,
            destination=self._send_destination,
            headers={"receipt": receipt},
        )
        try:
            await fut
        finally:
            self._listener.remove_future(receipt)

    async def _send_and_wait_for_response(self, request: Any, request_id: str):
        """ Send a message to the broker with a request ID and wait for the response
        """
        fut = self._loop.create_future()
        self._listener.add_future(request_id, fut)
        await self._send_request(request)
        message_id, headers, msg = cast(Tuple[str, Dict[str, str], Dict], await fut)
        return message_id, headers, msg

    async def _sign_artifact(
        self,
        typ: str,
        product: str,
        release_name: str,
        name: str,
        artifact: BinaryIO,
        sig_file: BinaryIO,
        sig_keyname: str,
        requestor: str,
    ):
        """ Sign an artifact
        """
        artifact_base64 = io.BytesIO()
        base64.encode(artifact, artifact_base64)
        request_id = (
            f'{product}-{typ}-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4()}'
        )
        message = {
            "artifact": artifact_base64.getvalue().decode(),
            "artifact_meta": {
                "product": product,
                "release_name": release_name,
                "name": name,
                "type": typ,
            },
            "request_id": request_id,
            "requestor": requestor,
            "sig_keyname": sig_keyname,
        }
        to_send = json.dumps(message)
        resp_message_id, _, resp_message = await self._send_and_wait_for_response(
            to_send, request_id=request_id
        )
        # example response: https://datagrepper.stage.engineering.redhat.com/id?id=2019-0304004b-d1e6-4e03-b28d-cfa1e5f59948&is_raw=true&size=extra-large
        await self._ack_message(resp_message_id)
        if resp_message["signing_status"] != "success":
            err = ", ".join(resp_message["errors"])
            raise IOError(f"Robo Signatory declined: {err}")
        input = io.BytesIO(resp_message["signed_artifact"].encode())
        base64.decode(input, sig_file)
        artifact_meta = cast(Dict[str, str], resp_message["artifact_meta"])
        return artifact_meta

    async def sign_json_digest(
        self, product: str, release_name: str, pullspec: str, digest: str, sig_file: BinaryIO
    ):
        """ Sign a JSON digest claim
        """
        json_claim = {
            "critical": {
                "image": {"docker-manifest-digest": digest},
                "type": "atomic container signature",
                "identity": {
                    "docker-reference": pullspec,
                },
            },
            "optional": {
                "creator": "Red Hat OpenShift Signing Authority 0.0.1",
            },
        }
        artifact = io.BytesIO(json.dumps(json_claim).encode())
        name = digest.replace(":", "=")
        signature_meta = await self._sign_artifact(
            typ="json-digest",
            product=product,
            release_name=release_name,
            name=name,
            artifact=artifact,
            sig_file=sig_file,
            sig_keyname=self.sig_keyname,
            requestor=self.requestor,
        )
        return signature_meta

    async def sign_message_digest(
        self, product: str, release_name: str, artifact: BinaryIO, sig_file: BinaryIO
    ):
        """ Sign a message digest
        """
        name = "sha256sum.txt.gpg"
        signature_meta = await self._sign_artifact(
            typ="message-digest",
            product=product,
            release_name=release_name,
            name=name,
            artifact=artifact,
            sig_file=sig_file,
            sig_keyname=self.sig_keyname,
            requestor=self.requestor,
        )
        return signature_meta
