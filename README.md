# fire_engine

`fire_engine` is a small private-by-default browser shell built on Qt WebEngine.
It provides tabs, popup handling, navigation, fullscreen video, per-session site
permissions, explicit downloads, zoom controls, render-process diagnostics, and
an off-the-record profile.

## Install and run on macOS

Use a virtual environment. Python 3.11 or 3.12 is recommended because GUI wheel
availability can lag behind the newest Python release.

```bash
cd /Users/ankeittaksh/Documents/git_codes/browser
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python browser.py
```

An optional initial address can be passed on the command line:

```bash
python browser.py https://www.youtube.com/
```

## Private-mode guarantees

The browser constructs a dedicated Qt WebEngine profile without a storage name.
That makes it off-the-record: cookies, cache, permissions, visited links, and web
storage are memory-only. Closing the browser destroys the profile. Downloads are
an explicit exception because the selected file is written to disk.

Private mode does not provide network anonymity. Websites, DNS providers, network
administrators, and internet providers can still observe traffic. TLS certificate
errors are never bypassed.

## YouTube and video codecs

Open **Tools → Media Diagnostics** to see what the installed Qt WebEngine build
can decode. WebM/VP9 or AV1 videos should work when the wheel includes those open
codecs. Some YouTube streams and many MP4 sites require H.264/AAC.

H.264/AAC support cannot be enabled by Python code or by installing the standalone
`ffmpeg` command. Qt WebEngine must itself be compiled with
`-webengine-proprietary-codecs`; distributing such a build may require codec
licences. The application enables JavaScript, WebGL, Media Source Extensions,
fullscreen, popup tabs, and normal desktop autoplay behavior, so a failed media
diagnostic points to the Qt build rather than the browser toolbar code.

The current PyQt6 WebEngine 6.11 wheel tested on this Mac reports VP9 and AV1 as
supported, but H.264/AAC and the Encrypted Media API as unavailable. Ordinary
YouTube videos can use VP9/AV1; DRM rentals and H.264-only media cannot play in
that wheel.

## Deliberately omitted

This project does not implement password storage, persistent history, account
sync, extensions, silent permissions, TLS-error bypasses, or background downloads.
Those features either conflict with private-by-default operation or require a much
larger security and maintenance surface.
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
