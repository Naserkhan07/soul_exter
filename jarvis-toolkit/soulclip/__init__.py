"""soulclip — turn a scene-by-scene script into one long video.

Give it a script split into scenes. For each scene it calls a text-to-video
provider, downloads the resulting clip, and when every scene is done it
stitches them together with ffmpeg into a single film.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
