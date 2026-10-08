"""Multimodal media analysis helpers: images, video frame batches, audio.

Adapted from ComfyUI-llama_Dapao (h3_video_prompt_node.py). Reference videos
are consumed as ComfyUI IMAGE frame batches (the alex_qwen_VL_model style),
so no cv2/imageio video decoding dependency is required.
"""

import base64
import io
import wave

import numpy as np
from PIL import Image

MIN_MEDIA_DURATION = 2.0
MAX_MEDIA_DURATION = 15.0

def tensor_to_data_uris(image_tensor):
    uris = []
    for index in range(image_tensor.shape[0]):
        array = np.clip(image_tensor[index].detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
        image = Image.fromarray(array).convert("RGB")
        uris.append(pil_to_data_uri(image, max_side=2048, quality=90))
    return uris


def pil_to_data_uri(image, max_side=1280, quality=86):
    image = image.convert("RGB")
    largest = max(image.size)
    if largest > max_side:
        scale = max_side / float(largest)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=int(quality), optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def analyze_video_tensor(frames_tensor, index, fps, sample_frames_per_second):
    """Analyze a reference video supplied as a ComfyUI IMAGE batch [N,H,W,C].

    Frames are interpreted at `fps`; `sample_frames_per_second` frames are
    sampled uniformly per second of the clip and sent to the LLM
    as analysis artifacts (never as extra <Picture N> sources).
    """
    frame_count = int(frames_tensor.shape[0])
    if frame_count < 1:
        raise ValueError(f"参考视频{index}至少需要1帧。")
    fps = float(fps)
    if fps <= 0:
        raise ValueError(f"参考视频{index}的帧率设置无效：{fps}。")
    duration = frame_count / fps
    if duration < MIN_MEDIA_DURATION - 0.05 or duration > MAX_MEDIA_DURATION + 0.05:
        raise ValueError(
            f"参考视频{index}时长为{duration:.2f}秒（{frame_count}帧/{fps:g}fps）；"
            f"H3要求每个视频为{MIN_MEDIA_DURATION:.0f}–{MAX_MEDIA_DURATION:.0f}秒。"
        )
    sample_count = max(1, int(sample_frames_per_second))
    total_samples = max(2, min(frame_count, round(duration * sample_count)))
    indices = sorted(set(np.linspace(0, frame_count - 1, total_samples).round().astype(int).tolist()))
    height, width = int(frames_tensor.shape[1]), int(frames_tensor.shape[2])
    frames = []
    for frame_index in indices:
        array = np.clip(frames_tensor[frame_index].detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
        image = Image.fromarray(array[..., :3]).convert("RGB")
        frames.append({
            "time": frame_index / fps,
            "uri": pil_to_data_uri(image, max_side=1024, quality=84),
        })
    return {
        "index": index,
        "duration": duration,
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "frames": frames,
    }

def normalize_audio(audio_input, index):
    if not isinstance(audio_input, dict):
        raise ValueError(f"无法读取参考音频{index}，请连接ComfyUI原生AUDIO输出。")
    waveform = audio_input.get("waveform")
    sample_rate = int(audio_input.get("sample_rate") or audio_input.get("sampler_rate") or 44100)
    if waveform is None:
        raise ValueError(f"参考音频{index}缺少waveform。")
    if sample_rate <= 0:
        raise ValueError(f"参考音频{index}采样率无效：{sample_rate}。")
    if hasattr(waveform, "detach"):
        waveform = waveform.detach().cpu().numpy()
    array = np.asarray(waveform)
    if array.ndim == 3:
        if array.shape[0] != 1:
            raise ValueError(f"参考音频{index}包含{array.shape[0]}个批次，请先拆分为单条音频。")
        array = array[0]
    array = np.squeeze(array)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    elif array.ndim == 2 and array.shape[0] > 8 and array.shape[1] <= 8:
        array = array.T
    if array.ndim != 2 or array.shape[0] > 8:
        raise ValueError(f"参考音频{index}声道格式无法识别。")
    if np.issubdtype(array.dtype, np.integer):
        maximum = max(abs(np.iinfo(array.dtype).min), np.iinfo(array.dtype).max)
        array = array.astype(np.float32) / float(maximum)
    else:
        array = array.astype(np.float32)
    array = np.nan_to_num(np.clip(array, -1.0, 1.0))
    duration = array.shape[1] / float(sample_rate)
    if duration < MIN_MEDIA_DURATION - 0.05 or duration > MAX_MEDIA_DURATION + 0.05:
        raise ValueError(
            f"参考音频{index}时长为{duration:.2f}秒；H3要求每个音频为"
            f"{MIN_MEDIA_DURATION:.0f}–{MAX_MEDIA_DURATION:.0f}秒。"
        )
    return array, sample_rate, duration


def audio_to_wav_base64(channels, sample_rate):
    pcm = (np.clip(channels.T, -1.0, 1.0) * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(int(pcm.shape[1]))
        output.setsampwidth(2)
        output.setframerate(int(sample_rate))
        output.writeframes(pcm.tobytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def audio_spectrogram_uri(mono, sample_rate):
    try:
        import librosa

        mel = librosa.feature.melspectrogram(
            y=mono,
            sr=sample_rate,
            n_fft=2048,
            hop_length=512,
            n_mels=128,
            power=2.0,
        )
        db = librosa.power_to_db(mel, ref=np.max)
    except Exception:
        frame_size = 2048
        hop = 512
        if mono.size < frame_size:
            mono = np.pad(mono, (0, frame_size - mono.size))
        windows = []
        for start in range(0, mono.size - frame_size + 1, hop):
            window = mono[start:start + frame_size] * np.hanning(frame_size)
            windows.append(np.abs(np.fft.rfft(window))[:256])
        spectrum = np.stack(windows or [np.zeros(256)], axis=1)
        db = 20.0 * np.log10(np.maximum(spectrum, 1e-6))
        db -= np.max(db)

    normalized = np.clip((db + 80.0) / 80.0, 0.0, 1.0)
    normalized = np.flipud(normalized)
    red = np.clip(normalized * 1.8, 0.0, 1.0)
    green = np.clip((normalized - 0.15) * 1.35, 0.0, 1.0)
    blue = np.clip(0.18 + normalized * 0.82, 0.0, 1.0)
    rgb = (np.stack([red, green, blue], axis=-1) * 255.0).astype(np.uint8)
    image = Image.fromarray(rgb).resize((1024, 512), Image.Resampling.BICUBIC)
    return pil_to_data_uri(image, max_side=1024, quality=88)


def analyze_audio(audio_input, index, include_raw_audio):
    channels, sample_rate, duration = normalize_audio(audio_input, index)
    mono = channels.mean(axis=0)
    rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))
    peak = float(np.max(np.abs(mono)))
    threshold = max(0.006, peak * 0.025)
    silence_ratio = float(np.mean(np.abs(mono) < threshold))
    bpm = 0.0
    try:
        import librosa

        tempo, _ = librosa.beat.beat_track(y=mono, sr=sample_rate)
        values = np.asarray(tempo).reshape(-1)
        bpm = float(values[0]) if values.size else 0.0
    except Exception:
        bpm = 0.0
    result = {
        "index": index,
        "duration": duration,
        "sample_rate": sample_rate,
        "channels": int(channels.shape[0]),
        "rms": rms,
        "peak": peak,
        "silence_ratio": silence_ratio,
        "bpm": bpm,
        "spectrogram_uri": audio_spectrogram_uri(mono, sample_rate),
    }
    if include_raw_audio:
        result["raw_wav_base64"] = audio_to_wav_base64(channels, sample_rate)
    return result
