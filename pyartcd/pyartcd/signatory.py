import base64
from datetime import datetime, timedelta
import json
import logging
from typing import Any, Dict
import uuid
import stomp
import asyncio
from asyncio.queues import Queue

_LOGGER = logging.getLogger(__name__)


class MyListener(stomp.ConnectionListener):
    def __init__(self, signatory: "Signatory", print_to_log=True):
        self._signatory = signatory
        self.print_to_log = print_to_log
        self._futures: Dict[str, asyncio.Future] = {}
        self._queue = Queue()

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
        receipt = frame.headers.get('receipt-id')
        if receipt:
            self._future_complete(receipt, None)

    def on_disconnected(self):
        self.__print("on_disconnected")

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
        timestamp = int(frame.headers.get('timestamp', '0')) / 1000
        if datetime.utcnow() - datetime.utcfromtimestamp(timestamp) >= timedelta(hours=2):
            _LOGGER.warning("Discard stale message {}".format(request_id))
            self._signatory._conn.ack(message_id, 1)  # discard the message
            return
        request_id = None
        try:
            msg = json.loads(frame.body)
            request_id = msg.get('request_id')
        except json.JSONDecodeError:
            _LOGGER.warning("Message type is not supported: %s", message_id)
        if not request_id:
            _LOGGER.warning("No request_id in message %s", message_id)
            self._signatory._conn.ack(message_id, 1)  # discard the message
            return
        fut = self._futures.get(request_id)
        if fut:
            fut.set_result((message_id, frame.headers, msg))
            del self._futures[request_id]

    def on_receipt(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_receipt %s %s", frame.headers, frame.body)
        receipt = frame.headers.get('receipt-id')
        if receipt:
            self._future_complete(receipt, frame.body)

    def on_error(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_error %s %s", frame.headers, frame.body)
        receipt = frame.headers.get('receipt-id')
        if receipt:
            self._future_exception(receipt, frame.headers.get('message'))

    def on_send(self, frame):
        """
        :param Frame frame: the stomp frame
        """
        self.__print("on_send %s %s %s", frame.cmd, frame.headers, frame.body)

    def on_heartbeat(self):
        self.__print("on_heartbeat")


def get_release_tag(release_name, arch):
    """Determine the quay destination tag where a release image lives, based on the
    release name and arch (since we can now have multiple arches for each release name)
    - make sure it includes the arch in the tag to distinguish from any other releases of same name.

    e.g.:
    (4.2.0-0.nightly-s390x-2019-12-10-202536, s390x) remains 4.2.0-0.nightly-s390x-2019-12-10-202536
    (4.3.0-0.nightly-2019-12-07-121211, x86_64) becomes 4.3.0-0.nightly-2019-12-07-121211-x86_64
    (4.9.0-0.nightly-arm64-2021-06-07-121211, aarch64) remains 4.9.0-0.nightly-arm64-2021-06-07-121211
    """
    go_arch_for = dict(aarch64="arm64", s390x="s390x", ppc64le="ppc64le", x86_64="amd64", multi="multi")
    return release_name if go_arch_for[arch] in release_name else "{}-{}".format(release_name, arch)


class Signatory:
    def __init__(self, stomp_config: dict) -> None:
        stomp_config = {
            'host_and_ports': [
                ('umb-broker03.stage.api.redhat.com', 61612),
                ('umb-broker04.stage.api.redhat.com', 61612),
            ],
        }
        self._loop = asyncio.get_event_loop()
        self._conn = stomp.Connection11(**stomp_config)
        self._conn.set_ssl(
            for_hosts=[
                ('umb-broker03.stage.api.redhat.com', 61612),
                ('umb-broker04.stage.api.redhat.com', 61612),
            ],
            cert_file="ssl/nonprod-openshift-art-bot.crt",
            key_file="ssl/nonprod-openshift-art-bot.key",
        )
        self._listener = MyListener(self)
        self._conn.set_listener('', self._listener)
        self._subscribed = False
        pass

    async def subscribe(self):
        # self._conn.subscribe(destination='/queue/Consumer.nonprod-openshift-art-bot.stage.VirtualTopic.eng.robosignatory.art.sign', id=1, ack='client')
        # self._conn.subscribe(destination='/queue/Consumer.nonprod-openshift-art-bot.stage.VirtualTopic.eng.art.artifact.sign', id=1, ack='client-individual')
        self._conn.subscribe(destination='/queue/Consumer.nonprod-openshift-art-bot.stage.VirtualTopic.eng.art.artifact.sign', id=1, ack='client-individual')
        self._subscribed = True

    async def unsubscribe(self):
        self._conn.unsubscribe(id=1)
        self._subscribed = False

    async def connect(self):
        receipt = str(uuid.uuid4())
        _LOGGER.info("Connecting...")
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.connect(wait=False, headers={
            'receipt': receipt
        })
        try:
            await fut
        finally:
            self._listener.remove_future(receipt)

    async def disconnect(self):
        receipt = str(uuid.uuid4())
        _LOGGER.info("Disconnecting...")
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.disconnect(receipt=receipt)
        try:
            await fut
        finally:
            self._listener.remove_future(receipt)

    async def send_signing_message(self, content: Any):
        receipt = str(uuid.uuid4())
        _LOGGER.info("Sending json digest message...")
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.send(
            body=content,
            destination='/topic/VirtualTopic.eng.art.artifact.sign',
            headers={
                'receipt': receipt
            }
        )
        try:
            await fut
        finally:
            self._listener.remove_future(receipt)

    async def send_and_wait_for_response(self, to_send: Any, request_id: str):
        fut = self._loop.create_future()
        self._listener.add_future(request_id, fut)
        await self.send_signing_message(to_send)
        message_id, headers, msg = await fut
        return message_id, headers, msg

    async def sign_ocp_payload(self, release_name: str, digest: str, sig_keyname='test', requestor='timer'):
        client_type = 'ocp-dev-preview'
        release_stage = "ocp-release-nightly" if client_type == 'ocp-dev-preview' else "ocp-release"
        # release_name = '4.11.0-0.nightly-multi-2023-02-21-004457'
        # digest = "sha256:70a26408942f5ecabd29e98933ed0bf715aa72b4b21974d1ecbf1eac31f82702"
        arch = 'multi'
        release_tag = get_release_tag(release_name, arch)

        request_id = f'openshift-json-digest-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        pullspec = "quay.io/openshift-release-dev/{}:{}".format(release_stage, release_tag)
        json_claim = {
            "critical": {
                "image": {
                    "docker-manifest-digest": digest
                },
                "type": "atomic container signature",
                "identity": {
                    "docker-reference": pullspec,
                }
            },
            "optional": {
                "creator": "Red Hat OpenShift Signing Authority 0.0.1",
            },
        }
        message = {
            "artifact": base64.b64encode(json.dumps(json_claim).encode()).decode(),
            "artifact_meta": {
                "product": "openshift",
                "release_name": release_name,
                "name": digest.replace(':', '='),
                "type": "json-digest",
            },
            "request_id": request_id,
            "requestor": requestor,
            "sig_keyname": sig_keyname,
        }
        to_send = json.dumps(message)
        message_id, headers, msg = await self.send_and_wait_for_response(to_send, request_id=request_id)
        await self.ack_message(message_id)
        print(msg)

    async def sign_message_digest(self, release_name: str, artifact_raw, sig_keyname='test', requestor='timer'):
        request_id = f'openshift-message-digest-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        message = {
            "artifact": base64.b64encode(json.dumps(artifact_raw).encode()).decode(),
            "artifact_meta": {
                "product": "openshift",
                "release_name": release_name,
                "name": "sha256sum.txt.gpg",
                "type": "message-digest",
            },
            "request_id": request_id,
            "requestor": requestor,
            "sig_keyname": sig_keyname,
        }
        to_send = json.dumps(message)
        message_id, headers, msg = await self.send_and_wait_for_response(to_send, request_id=request_id)
        await self.ack_message(message_id)
        print(msg)

    async def ack_message(self, message_id: str):
        receipt = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.ack(message_id, 1, receipt=receipt)
        await fut

    async def nack_message(self, message_id: str):
        receipt = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._listener.add_future(receipt, fut)
        self._conn.nack(message_id, 1, receipt=receipt)
        await fut

    async def recv_messages(self):
        while self._subscribed:
            yield await self._listener._queue.get()

    async def get_signature(self, request_id: str):
        async for header, body in self.recv_messages():
            message_id = header["message-id"]
            body = json.loads(body)
            _LOGGER.debug(json.dumps(body, indent=4))
            if body['request_id'] != request_id:
                # This received message doesn't match our request id
                print("Expecting request_id {}, but got {}".format(request_id, body['request_id']))
                if (datetime.utcnow() - datetime.utcfromtimestamp(body["timestamp"])) >= datetime.timedelta(hours=2):
                    _LOGGER.warning("Pop stale message {} off the bus.".format(request_id))
                    self._conn.ack(message_id, 1)
                else:
                    # Ignore it and continue receiving messages
                    self._conn.nack(message_id, 1)
                continue

            if body['signing_status'] != 'success':
                self._conn.ack(message_id, 1)
                raise IOError("ERROR: robosignatory failed to sign artifact")

            # example: https://datagrepper.stage.engineering.redhat.com/id?id=2019-0304004b-d1e6-4e03-b28d-cfa1e5f59948&is_raw=true&size=extra-large
            result = body['signed_artifact']
            out_file = body['artifact_meta']['name']
            raw_result = base64.decodestring(result)
            # with open(out_file, 'w') as fp:
            #     fp.write(base64.decodestring(result))
            #     fp.flush()
            # print("Wrote {} to disk".format(body['msg']['artifact_meta']['name']))
            self._conn.ack(message_id, 1)
            return raw_result
        return None
