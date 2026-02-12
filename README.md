# Ink/Stitch: An open source machine embroidery design platform based on Inkscape

## Fork Notice

This is a fork of [Ink/Stitch](https://github.com/inkstitch/inkstitch) that adds web API functionality for programmatic text-to-embroidery conversion.

### Added Features

**Text-to-Embroidery API** (`batch_text_to_pes.py`):
- FastAPI web service for converting text to embroidery files (.pes, .dst, .jef, etc.)
- RESTful API endpoints:
  - `GET /fonts` - List all available Ink/Stitch fonts with preview images
  - `GET /batch_text_to_pes` - Convert text to embroidery with customizable parameters (font, scale, trim, alignment, spacing)
  - `GET /fonts/preview/{font_name}` - Serve font preview images
- Can be used as a CLI tool or imported as a Python library
- Includes response caching and async processing for performance
- Supports all Ink/Stitch lettering options (trim, color sorting, text alignment, letter/word/line spacing)

**Docker Deployment Options**:
- `Dockerfile`: Full installation using Ubuntu 24.04 and uv package manager
- `Dockerfile.api`: Lightweight build without GUI dependencies (~3-5 minute build time vs 20+ minutes)
- `Dockerfile.simple`: Minimal API-only build without wxPython or PyGObject
- `Dockerfile.working`: Optimized build that copies inkex from local venv to avoid compilation issues

See `DOCKER_DEPLOYMENT.md` for deployment instructions.

---

Want to design embroidery pattern files (PES, DST, and many more) using **free, open source software?**

![Ink/Stitch Logo](images/logos/inkstitch_colour_logo.svg)

Ink/Stitch aims to be a full-fledged embroidery digitizing platform based entirely on free, open source software.  Our goal is to be approachable for hobbyists while also providing the power needed by professional digitizers.  We also aim to provide a welcoming open source environment where contributing is fun and easy.

Want to learn more?

* Check out our list of [features](https://inkstitch.org/features/)
* [Quick Install](https://inkstitch.org/docs/install/) on Linux, Windows and Mac
* See some [photos](https://inkstitch.org/tutorials/inspiration/) showing what Ink/Stitch can do
* Watch some [videos](https://inkstitch.org/tutorials/video/) of Ink/Stitch in action
* ...and lots more on our [website](https://inkstitch.org)

Need help?

* Contact us via the [Inkscape Forum](https://inkscape.org/forums/embroidery/)
* Join our [chat channel](https://chat.inkscape.org/channel/inkstitch)

# Background and Philosophy

_by @lexelby, an Ink/Stitch programmer_

I received a really wonderful christmas gift for a geeky programmer hacker: an embroidery machine.  It's pretty much a CNC thread-bot... I just had to figure out how to design programs for it.  The problem is, **all free embroidery design software seemed to be terrible**, especially when you add in the requirement of being able to run in Linux, my OS of choice.

I started off hacking on [inkscape-embroidery](http://www.jonh.net/~jonh/inkscape-embroidery/).  It had some of the basic capabilities I needed, and I saw a lot of potential.  I love the idea of using an existing, ultra-powerful SVG editor as the basis for an embroidery design suite.

Things took off from there.  I continued adding features as I needed them, and by this point, very little if any of the original code remains.

The goal of Ink/Stitch is to provide a powerful embroidery digitizing platform for everyone **completely free**.  I want to open up the field of embroidery design, making it approachable even for those who can't spend hundreds or thousands of dollars on software.  And I want folks like me, who love to combine code with art, to have an open, extensible, and approachable platform to hack on.
