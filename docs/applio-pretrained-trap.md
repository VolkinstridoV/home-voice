# Applio trained from scratch without saying so

Three hours of a night of CPU training produced pure noise. Whisper heard
nothing in any checkpoint probe, at any pitch or index rate.

## Cause

`python core.py prerequisites --pretraineds-hifigan --models` printed
`Prerequisites installed successfully.` — but `rvc/models/pretraineds/hifi-gan/`
stayed empty (only `.gitkeep`). `rvc/models/predictors/rmvpe.pt` was missing
too; a second `prerequisites --models` run did download it.

Then `rvc/lib/tools/pretrained_selector.py`:

```python
if os.path.exists(path_g) and os.path.exists(path_d):
    return path_g, path_d
else:
    return "", ""
```

With `--pretrained` requested and the files absent, training silently starts
from random weights. Nothing in the console says so. The only tell is the
*absence* of two lines:

```
Loaded pretrained (G) 'rvc/models/pretraineds/hifi-gan/f0G48k.pth'
Loaded pretrained (D) 'rvc/models/pretraineds/hifi-gan/f0D48k.pth'
```

## Fix

Download the pretrained pair directly and check the log before walking away:

```
https://huggingface.co/IAHispano/Applio/resolve/main/Resources/pretrained_v2/f0G48k.pth
https://huggingface.co/IAHispano/Applio/resolve/main/Resources/pretrained_v2/f0D48k.pth
```

With the pretrained loaded, epoch 2 already had a lower generator loss (37)
than epoch 30 from scratch (45), and the epoch-10 probe was fully intelligible
to Whisper.

## Two more CPU/Docker gotchas

- The DataLoader workers need shared memory: run the container with
  `--shm-size=4g`, or the first epoch dies with
  `unable to allocate shared memory(shm)`.
- Killing `core.py train` leaves the spawned training worker alive as an
  orphan; it keeps eating CPU and writing checkpoints. Kill the
  `multiprocessing.spawn` worker too.

An issue for the silent fallback is filed upstream (see the repository's
README for the link).
