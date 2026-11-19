# Tool commands

All the real work (PDF pages, voice, Manim, ffmpeg) goes through one command line tool:

```sh
bin/py -m papervid.tools <command> [options]
```

Run it from the project folder. Every command prints JSON, and every result has an `ok` field. If `ok` is `false`, look at `error` or `stderr_tail` to see what went wrong.

`<work_dir>` below always means a video's folder, like `papervid_output/my_paper`.

Many commands take `--scene`. You can give it `all`, one number (`3`), a list (`1,4`) or a range (`2-5`).

## doctor

Checks that every tool and package is installed.

```sh
bin/py -m papervid.tools doctor
```

It shows which Python is running, the Manim version, and whether LaTeX equations work (`mathtex`). Anything in `missing` must be installed before you go on.

## init

Makes the video folder and turns each PDF page into a PNG.

```sh
bin/py -m papervid.tools init <pdf> [--slug NAME] [--out DIR] [--dpi 150] [--max-pages 40] [--force]
```

- `--slug`: the folder name. By default it comes from the PDF's title or file name.
- `--out`: where to make the folder. Default is `papervid_output`.
- `--dpi`: page image quality. Default is 150.
- `--max-pages`: only render this many pages. Default is 40.
- `--force`: render the pages again even if they already exist.

It's safe to run twice. Pages that are already there get reused.

## status

Shows how far a video has got.

```sh
bin/py -m papervid.tools status <work_dir>
```

For each scene you see whether it has audio, code, a low and high quality render, and a review. Use it to pick up where you left off.

## validate

Checks `script.json` for mistakes.

```sh
bin/py -m papervid.tools validate <work_dir>
```

It prints `errors`, `warnings` and an outline with the word count and estimated length of each scene.

## crop

Cuts the figures listed in `script.json` out of the page images.

```sh
bin/py -m papervid.tools crop <work_dir>
```

The images go to `figures/<name>.png`. Open them to check the box is tight, change the box if needed, and run `crop` again.

## voices

Lists the edge-tts voices.

```sh
bin/py -m papervid.tools voices [--locale en-]
```

Use `--locale en-GB` or `--locale de-` and so on to see other languages.

## tts

Records the narration for each scene.

```sh
bin/py -m papervid.tools tts <work_dir> [--scene all] [--voice en-US-AndrewNeural] [--rate +0%] [--pitch +0Hz] [--force]
```

- It writes `audio/scene_NN.mp3` and saves `audio_duration` into `script.json`.
- Scenes whose words haven't changed are skipped. Use `--force` to record them again.
- `--rate` makes the voice faster or slower, like `+10%` or `-5%`.

Run this before you build any scene. Every scene is timed to its audio.

## render

Renders scene files with Manim.

```sh
bin/py -m papervid.tools render <work_dir> [--scene all] [--quality l] [--timeout 900]
```

| Quality | Size | Use it for |
| --- | --- | --- |
| `l` | 480p, 15 fps | Fast checks while you build |
| `m` | 720p, 30 fps | Drafts |
| `h` | 1080p, 60 fps | The final video |

High quality is slow. For a long video, render in chunks like `--scene 1-4`, then `--scene 5-8`.

## frames

Pulls sample frames out of a render so you can look at it.

```sh
bin/py -m papervid.tools frames <work_dir> --scene 3 [--count 6] [--quality l] [--video PATH]
```

The JPGs go to `frames/scene_03/`. Each file name has the time it was taken from.

## assemble

Adds the audio to each scene and joins all scenes into one video.

```sh
bin/py -m papervid.tools assemble <work_dir> [--quality h] [--allow-lower] [--output final.mp4]
```

- If the narration is longer than a scene's video, it holds the last frame.
- By default every scene needs a render at the quality you ask for. `--allow-lower` lets it use a lower quality render when the right one is missing.
