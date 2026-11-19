# The llama.cpp pipeline

This is the other way to run papervid. It doesn't use Claude. A local model running in llama.cpp writes the script, and papervid builds the scenes from ready-made templates.

It's simpler and fully offline (apart from the voice), but the videos are more basic than the Claude Code ones.

## Start the model server

Start the llama.cpp server with any model you like:

```sh
llama-server -m your-model.gguf -c 8192 --port 8080
```

If the model can read images, papervid can also use it to check rendered frames.

## Run it

```sh
bin/py main.py
```

Or give it the PDF straight away:

```sh
bin/py main.py papers/my_paper.pdf
```

It walks you through seven steps and asks a question at each one:

1. **Pick the PDF.**
2. **Render the pages** as images.
3. **Connect to llama.cpp.** It asks for the server address (default `http://localhost:8080`) and the model name. If it can't reach the server, it makes a test script instead so you can still try the rest.
4. **Write the script.** The model reads the paper and writes the scenes.
5. **Review the script.** You see a table of the scenes. You can open the details of each one, then carry on. (There's also a `regenerate` choice, but it doesn't do anything yet.)
6. **Pick a voice** for the narration.
7. **Render the video.** You can turn on frame checking, where the model looks at rendered frames and asks for a scene to be redone if it looks wrong.

## Where the code is

| File | What it does |
| --- | --- |
| `main.py` | Starts the menu |
| `papervid/cli.py` | The seven steps |
| `papervid/generators/` | Talks to llama.cpp and writes the script |
| `papervid/builder/` | Turns the script into Manim code from templates |
| `papervid/renderer/video_render.py` | Renders and joins the video |
| `papervid/renderer/frame_verify.py` | Sends frames to the model for checking |
| `papervid/config/` | Default settings like the server address and voice |

The two pipelines share the PDF, voice and ffmpeg code. They don't share the script writing or the scene building.
