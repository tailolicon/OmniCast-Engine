"""Gemini reference conditioning — the wiring that makes a token mean a file.

`_build_contents` is the whole contract: labels and images interleave so
"[IMAGE 2]:" sits directly against the bytes it names. These tests need no API
key, because assembly happens before any client is created — deliberately, so
a caller's mistake surfaces as itself rather than as a generic API failure.
"""

from __future__ import annotations

import pytest

from omnicast.media.providers.image_gemini import GeminiImageProvider, MediaError

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff" + b"0" * 64


@pytest.fixture
def provider():
    return GeminiImageProvider()


@pytest.fixture
def images(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.jpg"
    a.write_bytes(PNG)
    b.write_bytes(JPG)
    return str(a), str(b)


def test_the_provider_declares_that_it_honours_references(provider):
    """Callers check this flag; a provider that accepts references and ignores
    them produces drift that reads as a prompt-writing bug."""
    assert provider.supports_reference_images is True
    assert provider.max_reference_images >= 2


def test_no_references_sends_the_bare_prompt(provider):
    """Unconditioned generation must keep behaving exactly as it did."""
    assert provider._build_contents("a lighthouse", None, None) == "a lighthouse"
    assert provider._build_contents("a lighthouse", [], []) == "a lighthouse"


def test_each_label_immediately_precedes_the_image_it_names(provider, images):
    contents = provider._build_contents("[IMAGE 1] stands in [IMAGE 2]",
                                        list(images), ["[IMAGE 1]", "[IMAGE 2]"])

    assert contents[0] == "[IMAGE 1]:"
    assert contents[2] == "[IMAGE 2]:"
    assert contents[-1] == "[IMAGE 1] stands in [IMAGE 2]"
    assert not isinstance(contents[1], str)
    assert not isinstance(contents[3], str)


def test_labels_default_to_one_based_numbering(provider, images):
    contents = provider._build_contents("x", list(images), None)

    assert [c for c in contents if isinstance(c, str)][:2] == \
        ["[IMAGE 1]:", "[IMAGE 2]:"]


def test_a_mismatched_label_count_is_refused(provider, images):
    """Off-by-one here binds every token to the wrong file — silently."""
    with pytest.raises(MediaError, match="mismatched pairing"):
        provider._build_contents("x", list(images), ["[IMAGE 1]"])


def test_a_missing_reference_is_refused_rather_than_skipped(provider, tmp_path):
    """Skipping element 2 would slide element 3 into its place and re-point
    every later token in the prompt."""
    with pytest.raises(MediaError, match="renumber"):
        provider._build_contents("x", [str(tmp_path / "gone.png")], None)


def test_an_empty_reference_file_is_refused(provider, tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")

    with pytest.raises(MediaError, match="missing or empty"):
        provider._build_contents("x", [str(empty)], None)


def test_going_over_the_cap_is_the_callers_decision(provider, images):
    """This layer refuses rather than silently truncating: only the caller
    knows which reference matters least."""
    too_many = [images[0]] * (provider.max_reference_images + 1)

    with pytest.raises(MediaError, match="exceeds"):
        provider._build_contents("x", too_many, None)
