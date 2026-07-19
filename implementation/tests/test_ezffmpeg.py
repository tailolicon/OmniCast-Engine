import pytest
from omnicast.media.render_engine import EZFFMPEG

def test_ezffmpeg_basic_video():
    builder = EZFFMPEG()
    builder.add_video("bg.mp4")
    
    # Simple direct copy or basic concat
    args = builder.build("output.mp4")
    assert "-i" in args
    assert "bg.mp4" in args
    assert "output.mp4" in args

def test_ezffmpeg_video_with_audio_ducking():
    builder = EZFFMPEG()
    builder.add_video("bg.mp4")
    builder.add_audio("voiceover.wav", type="voice", delay_ms=0)
    builder.add_audio("bgm.mp3", type="bgm", ducking=True)
    
    args = builder.build("output.mp4")
    
    cmd_str = " ".join(args)
    assert "-filter_complex" in cmd_str
    assert "amix" in cmd_str or "amerge" in cmd_str
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd_str
    assert "aresample=48000" in cmd_str
    assert "aformat=channel_layouts=stereo" in cmd_str
    assert "-b:a 192k" in cmd_str
    assert "-ar 48000" in cmd_str
    assert "-ac 2" in cmd_str

def test_ezffmpeg_single_audio_is_mastered():
    builder = EZFFMPEG()
    builder.add_video("bg.mp4")
    builder.add_audio("voiceover.wav", type="voice")

    args = builder.build("output.mp4")
    cmd_str = " ".join(args)
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd_str
    assert "-map [a_master]" in cmd_str
    
def test_ezffmpeg_video_with_subtitles():
    builder = EZFFMPEG()
    builder.add_video("bg.mp4")
    builder.add_subtitle("subs.srt")
    
    args = builder.build("output.mp4")
    cmd_str = " ".join(args)
    assert "subtitles=subs.srt" in cmd_str

def test_ezffmpeg_pts_alignment():
    builder = EZFFMPEG()
    builder.add_video("clip1.mp4")
    builder.add_video("clip2.mp4")
    
    args = builder.build("output.mp4")
    cmd_str = " ".join(args)
    assert "concat=n=2:v=1:a=0" in cmd_str
