FROM michaelfong2017/l4t-base-r32.6.1-py3.8-opencv4.5.3:latest

RUN apt update && apt install -y libavdevice-dev libavfilter-dev libopus-dev libvpx-dev pkg-config libsrtp2-dev

# Using FFmpeg with NVIDIA GPU Hardware Acceleration
WORKDIR /
RUN git clone https://git.videolan.org/git/ffmpeg/nv-codec-headers.git
WORKDIR /nv-codec-headers
RUN make install
WORKDIR /
RUN git clone https://git.ffmpeg.org/ffmpeg.git ffmpeg/
WORKDIR /ffmpeg
RUN git checkout -t origin/release/4.3 && cat RELEASE && apt update && apt install -y build-essential yasm cmake libtool libc6 libc6-dev unzip wget libnuma1 libnuma-dev
RUN ./configure --enable-nonfree --enable-cuda-nvcc --enable-libnpp --extra-cflags=-I/usr/local/cuda/include --extra-ldflags=-L/usr/local/cuda/lib64 --disable-static --enable-shared
RUN make -j 8
RUN make install
ENV LD_LIBRARY_PATH="/ffmpeg/libavdevice:/ffmpeg/libavfilter:/ffmpeg/libavformat:/ffmpeg/libavcodec:/ffmpeg/libavformat:/ffmpeg/libswresample:/ffmpeg/libswscale:/ffmpeg/libavutil:$LD_LIBRARY_PATH"
ENV PATH="/ffmpeg:$PATH"

# Build PyAV from source
WORKDIR /
RUN apt update && apt install -y libffi-dev
RUN git clone https://github.com/PyAV-Org/PyAV.git
WORKDIR /PyAV
RUN git checkout tags/v8.0.3 && python -m pip install --upgrade pip && pip install --upgrade -r tests/requirements.txt
RUN mkdir -p vendor/ && cp -r /ffmpeg vendor/
RUN make


WORKDIR /
RUN mkdir /app
WORKDIR /app
ADD requirements.txt /app
RUN pip install --upgrade pip && pip install -r requirements.txt

RUN ln -s /PyAV/build/lib.linux-aarch64-3.8/av /usr/lib/python3/dist-packages/av

ADD . /app

CMD ["python", "main.py"]
