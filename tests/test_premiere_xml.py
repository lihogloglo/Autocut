from pathlib import Path

from autocut.premiere_xml import pathurl_to_path


def test_pathurl_forms():
    expected = Path("D:/Rushes/A7S3/C0001.MP4")
    assert pathurl_to_path("file://localhost/D%3a/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("file:///D:/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("D:/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("file://localhost/D:/Mes%20rushes/prise%201.wav") == Path("D:/Mes rushes/prise 1.wav")
