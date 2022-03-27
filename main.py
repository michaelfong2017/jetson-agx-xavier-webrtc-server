import argparse
import asyncio
from dataclasses import dataclass
import json
import logging
import os
import ssl
import uuid

import cv2
from aiohttp import web
from av import VideoFrame
import aiohttp_cors
from aiortc import (
    MediaStreamTrack,
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
)
from aioice import Candidate
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder, MediaRelay

from detector import *
import time
import threading

from task_manager import TaskManager

ROOT = os.path.dirname(__file__)

logger = logging.getLogger()
pcs = {}
relay = MediaRelay()


class VideoTransformTrack(MediaStreamTrack):
    """
    A video stream track that transforms frames from an another track.
    """

    kind = "video"

    def __init__(self, track, task_manager):
        super().__init__()  # don't forget this!
        self.track = track
        self.task_manager = task_manager

        self.detector = Detector()

    async def recv(self):
        frame = await self.track.recv()

        if self.task_manager.task == "cartoon":
            img = frame.to_ndarray(format="bgr24")

            # prepare color
            img_color = cv2.pyrDown(cv2.pyrDown(img))
            for _ in range(6):
                img_color = cv2.bilateralFilter(img_color, 9, 9, 7)
            img_color = cv2.pyrUp(cv2.pyrUp(img_color))

            # prepare edges
            img_edges = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            img_edges = cv2.adaptiveThreshold(
                cv2.medianBlur(img_edges, 7),
                255,
                cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY,
                9,
                2,
            )
            img_edges = cv2.cvtColor(img_edges, cv2.COLOR_GRAY2RGB)

            # combine color and edges
            try:
                img = cv2.bitwise_and(img_color, img_edges)
            except:
                pass

            # Mirror image for selfie
            if self.task_manager.mirror:
                img = cv2.flip(img, 1)

            # rebuild a VideoFrame, preserving timing information
            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame
        elif self.task_manager.task == "edges":
            # perform edge detection
            img = frame.to_ndarray(format="bgr24")
            img = cv2.cvtColor(cv2.Canny(img, 100, 200), cv2.COLOR_GRAY2BGR)

            # Mirror image for selfie
            if self.task_manager.mirror:
                img = cv2.flip(img, 1)

            # rebuild a VideoFrame, preserving timing information
            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame
        elif self.task_manager.task == "rotate":
            # rotate image
            img = frame.to_ndarray(format="bgr24")
            rows, cols, _ = img.shape
            M = cv2.getRotationMatrix2D((cols / 2, rows / 2), frame.time * 45, 1)
            img = cv2.warpAffine(img, M, (cols, rows))

            # Mirror image for selfie
            if self.task_manager.mirror:
                img = cv2.flip(img, 1)
            
            # rebuild a VideoFrame, preserving timing information
            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame
        elif self.task_manager.task == "object detection":
            ts = time.time()

            img = frame.to_ndarray(format="bgr24")
            te = time.time()
            logger.debug("{} {:.3f} sec".format("to_ndarray", te - ts))
            ts = te

            self.detector.thread = threading.Thread(
                target=self.detector.detect, args=(img,)
            )
            self.detector.thread.start()
            if self.detector.img is not None:
                img = self.detector.img
            te = time.time()
            logger.debug("{} {:.3f} sec".format("detect", te - ts))
            ts = te

            # Mirror image for selfie
            if self.task_manager.mirror:
                img = cv2.flip(img, 1)

            # rebuild a VideoFrame, preserving timing information
            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            te = time.time()
            logger.debug("{} {:.3f} sec".format("from_ndarray", te - ts))
            ts = te

            return new_frame
        else:
            img = frame.to_ndarray(format="bgr24")
            # Mirror image for selfie
            if self.task_manager.mirror:
                img = cv2.flip(img, 1)

            # rebuild a VideoFrame, preserving timing information
            new_frame = VideoFrame.from_ndarray(img, format="bgr24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base

            return new_frame


async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"].lower())

    pc = RTCPeerConnection(
        RTCConfiguration(
            # iceServers=[
            #     RTCIceServer(
            #         urls="turn:16.163.180.160:3478",
            #         username=USER,
            #         credential=CREDENTIAL,
            #     )
            # ]
        )
    )
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs[pc_id] = pc

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Created for %s", request.remote)

    # prepare local media
    recorder = MediaBlackhole()

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str) and message.startswith("ping"):
                channel.send("pong" + message[4:])

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            del pcs[pc_id]

    @pc.on("track")
    def on_track(track):
        log_info("Track %s received", track.kind)

        if track.kind == "audio":
            recorder.addTrack(track)
        elif track.kind == "video":
            task_manager = TaskManager(mirror=json.loads(params["mirror"].lower()), task=params["video_transform"])
            pc.addTrack(
                VideoTransformTrack(
                    relay.subscribe(track), task_manager=task_manager
                )
            )

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)
            await recorder.stop()

    # handle offer
    await pc.setRemoteDescription(offer)
    await recorder.start()

    # send answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "pc_id": pc_id}
        ),
    )


@dataclass
class IceCandidate(Candidate):
    candidate: str = ""
    sdpMid: str = ""
    sdpMLineIndex: str = ""
    ip: str = ""
    relatedAddress: str = ""
    relatedPort: int = -1
    protocol: str = ""
    tcpType: str = ""

async def new_ice_candidate(request):
    params = await request.json()
    ice_candidate: IceCandidate = Candidate.from_sdp(params["candidate"])
    ice_candidate.candidate = params["candidate"]
    ice_candidate.sdpMid = params["sdpMid"]
    ice_candidate.sdpMLineIndex = params["sdpMLineIndex"]
    ice_candidate.ip = ice_candidate.host
    ice_candidate.relatedAddress = ice_candidate.related_address
    ice_candidate.relatedPort = ice_candidate.related_port
    ice_candidate.protocol = ice_candidate.transport
    ice_candidate.tcpType = ice_candidate.tcptype
    pc_id = params["pc_id"]
    # print(ice_candidate)
    await pcs[pc_id].addIceCandidate(ice_candidate)
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"pc_id": pc_id}
        ),
    )


async def set_mirror(request):
    params = await request.json()
    task_manager = TaskManager()
    mirror = True if params["mirror"] == "true" else False if params["mirror"] == "false" else None
    task_manager.set_mirror(mirror)
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"mirror_received": mirror}
        ),
    )


async def set_task(request):
    params = await request.json()
    task_manager = TaskManager()
    task_manager.set_task(params["task"])
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"task_received": params["task"]}
        ),
    )


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc_id, pc in pcs.items()]
    await asyncio.gather(*coros)
    pcs.clear()


app = web.Application()
cors = aiohttp_cors.setup(app)
app.on_shutdown.append(on_shutdown)
app.router.add_get("/", index)
app.router.add_get("/client.js", javascript)
app.router.add_post("/offer", offer)
app.router.add_post("/new-ice-candidate", new_ice_candidate)
app.router.add_post("/set-mirror", set_mirror)
app.router.add_post("/set-task", set_task)

for route in list(app.router.routes()):
    cors.add(
        route,
        {
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*",
            )
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WebRTC audio / video / data-channels demo"
    )
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument("--record-to", help="Write received media to a file."),
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    web.run_app(
        app, access_log=None, host=args.host, port=args.port, ssl_context=ssl_context
    )
