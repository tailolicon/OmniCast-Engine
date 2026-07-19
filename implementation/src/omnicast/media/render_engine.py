import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

AUDIO_MASTER_FILTER = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo"

@dataclass
class VideoInput:
    path: str
    has_audio: bool = False

@dataclass
class AudioInput:
    path: str
    type: str  # "voice" or "bgm"
    ducking: bool = False
    delay_ms: int = 0

class EZFFMPEG:
    """Builder pattern for constructing complex FFmpeg commands."""
    
    def __init__(self):
        self.videos: List[VideoInput] = []
        self.audios: List[AudioInput] = []
        self.subtitle_path: Optional[str] = None
        self.options: Dict[str, str] = {}
        
    def add_video(self, path: str, has_audio: bool = False) -> "EZFFMPEG":
        self.videos.append(VideoInput(path=path, has_audio=has_audio))
        return self
        
    def add_audio(self, path: str, type: str = "bgm", ducking: bool = False, delay_ms: int = 0) -> "EZFFMPEG":
        self.audios.append(AudioInput(path=path, type=type, ducking=ducking, delay_ms=delay_ms))
        return self
        
    def add_subtitle(self, path: str) -> "EZFFMPEG":
        self.subtitle_path = path
        return self
        
    def build(self, output_path: str) -> List[str]:
        """Compile the inputs and filters into an FFmpeg command argument list."""
        cmd = ["ffmpeg", "-y"]
        
        # Add all inputs
        for v in self.videos:
            cmd.extend(["-i", v.path])
        for a in self.audios:
            cmd.extend(["-i", a.path])
            
        filter_complex = []
        
        # 1. Video Concat or Direct
        video_inputs_count = len(self.videos)
        if video_inputs_count > 1:
            concat_filter = f"concat=n={video_inputs_count}:v=1:a=0[v_out]"
            filter_complex.append("".join(f"[{i}:v:0]" for i in range(video_inputs_count)) + concat_filter)
            last_v = "[v_out]"
        elif video_inputs_count == 1:
            last_v = "[0:v:0]"
        else:
            raise ValueError("EZFFMPEG requires at least 1 video input.")
            
        # 2. Subtitles
        if self.subtitle_path:
            # Escape path for FFmpeg filter
            escaped_path = self.subtitle_path.replace("\\", "/").replace(":", "\\:")
            sub_filter = f"{last_v}subtitles={escaped_path}[v_sub]"
            filter_complex.append(sub_filter)
            last_v = "[v_sub]"
            
        # 3. Audio Mixing + final mastering gate
        audio_streams = []
        for idx, a in enumerate(self.audios):
            stream_idx = video_inputs_count + idx
            audio_streams.append(f"[{stream_idx}:a:0]")
            
        last_a = None
        if audio_streams:
            if len(audio_streams) > 1:
                # Basic amix for now. Advanced ducking requires sidechaincompress
                amix_filter = "".join(audio_streams) + f"amix=inputs={len(audio_streams)}:duration=longest[a_mix]"
                filter_complex.append(amix_filter)
                audio_source = "[a_mix]"
            else:
                audio_source = audio_streams[0]
            filter_complex.append(f"{audio_source}{AUDIO_MASTER_FILTER}[a_master]")
            last_a = "[a_master]"
                
        # Assemble final command
        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])
            cmd.extend(["-map", last_v])
            if last_a:
                cmd.extend(["-map", last_a])
        else:
            # If no filters, just map video and audio directly
            cmd.extend(["-map", "0:v:0"])
            if self.audios:
                cmd.extend(["-map", f"{video_inputs_count}:a:0"])
                
        # Common encoding settings for YouTube Shorts
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            output_path
        ])
        
        return cmd
