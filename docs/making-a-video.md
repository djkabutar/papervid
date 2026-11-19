# Making a video with Claude Code

This is the main way to use papervid. You give Claude a PDF and it does the rest.

## The command

Open Claude Code in the project folder and type:

```
/papervid papers/my_paper.pdf
```

Options:

| Option | What it does | Default |
| --- | --- | --- |
| `--voice <name>` | The edge-tts voice for the narration | `en-US-AndrewNeural` |
| `--scenes <n>` | How many scenes to make | Claude picks, usually 6 to 12 |
| `--quality h` or `m` | Final video quality. `h` is 1080p60, `m` is 720p30 and faster | `h` |
| `--auto` | Don't stop to ask you to approve the outline | off |

Example:

```
/papervid papers/attention.pdf --voice en-GB-RyanNeural --quality m --auto
```

To see all the voices, run `bin/py -m papervid.tools voices`.

## What happens, step by step

1. **Check the tools.** Claude runs `doctor`. If something is missing, it stops and tells you.
2. **Set up a folder.** `init` makes `papervid_output/<name>/` and turns every PDF page into a PNG.
3. **Read the paper.** Claude reads the PDF and finds the problem, the main idea, the key equations, the method, the results and the takeaways.
4. **Write the script.** Claude writes `script.json`. Each scene has the spoken words, a plan for the visuals, and any figures to cut out of the paper. See [script-json.md](script-json.md).
5. **Cut out figures.** `crop` cuts the figures out of the page images. Claude looks at each one and fixes the box until it's tight.
6. **You approve the outline.** Claude shows a table of scenes and asks you to approve, revise, make it shorter, or add more depth. With `--auto` this step is skipped.
7. **Record the voice.** `tts` makes one MP3 per scene and saves how long each one is. This has to happen before the scenes are built, because every scene is timed to its audio.
8. **Build the scenes.** Claude starts a `manim-scene` helper for each scene, three at a time. Each helper writes `scenes/scene_NN.py`, renders it at low quality, looks at the frames, fixes problems, and saves a review.
9. **Render in high quality.** `render --quality h` renders every scene again at full quality.
10. **Put it together.** `assemble` adds the audio to each scene and joins them into `final.mp4`.
11. **Report.** Claude tells you where the file is, how long it is, and about any scene with known problems.

## The output folder

Everything for one video lives in `papervid_output/<name>/`:

```
meta.json              info about the PDF
script.json            the script (you can edit this)
pages/page_NNN.png     every page of the PDF as an image
figures/<name>.png     figures cut out of the pages
audio/scene_NN.mp3     the narration, one file per scene
scenes/scene_NN.py     the Manim code, one file per scene
renders/               rendered clips at each quality
frames/scene_NN/       sample frames and review.json for each scene
final.mp4              the finished video
```

## Changing a video after it's made

You don't have to start over. Edit what you want, then run the same `/papervid` command again. It checks what is already done and only redoes what changed.

- **Change the words.** Edit `narration` in `script.json`. The voice is recorded again only for that scene. The scene code may need a fix too, because its timing changes.
- **Change the visuals.** Edit `visual_plan` in `script.json`, or edit `scenes/scene_NN.py` directly.
- **Fix one scene by hand.** Edit the scene file, then run:

  ```sh
  bin/py -m papervid.tools render papervid_output/<name> --scene 4 --quality h
  bin/py -m papervid.tools assemble papervid_output/<name> --quality h
  ```

To see where a video stands at any time:

```sh
bin/py -m papervid.tools status papervid_output/<name>
```

## Using more than one source

`init` takes one PDF. If you want a video built from several papers, join them into one PDF first:

```sh
mkdir -p papervid_output/my_topic
pdfunite paper1.pdf paper2.pdf papervid_output/my_topic/source.pdf
bin/py -m papervid.tools init papervid_output/my_topic/source.pdf --slug my_topic --max-pages 80
```

Then run `/papervid papervid_output/my_topic/source.pdf`. Raise `--max-pages` if the joined file has more than 40 pages, because `init` stops at 40 pages by default.

Images that aren't in a PDF (for example from a web page) can be copied straight into the `figures/` folder. Mention them in the scene's `visual_plan` so the scene helper knows to use them.

## Tips

- Short videos come out better. 3 to 7 minutes is a good target.
- Draft with `--quality m` first. It renders much faster. Use `h` once you're happy.
- Manim is heavy on the CPU. Three scenes at once is about right for most machines.
