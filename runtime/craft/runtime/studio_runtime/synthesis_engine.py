"""Trusted, offline SDXL runner; requires separately authorized local provision."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
root=Path(sys.argv[1]).resolve(); call=json.loads((root/'call.json').read_text()); provision=call['provision']; recipe=json.loads((root/'recipe.json').read_text())
for package,version in provision['versions'].items():
    assert importlib.metadata.version(package)==version, 'Inference library version differs: '+package
import torch
from diffusers import StableDiffusionXLPipeline, StableDiffusionXLInpaintPipeline, EulerDiscreteScheduler
from PIL import Image, ImageChops

device=provision['device']; assert device in ('cpu','mps','cuda')
if device=='mps': assert torch.backends.mps.is_available(), 'MPS unavailable'
if device=='cuda': assert torch.cuda.is_available(), 'CUDA unavailable'
torch.set_num_threads(8)
dtype=torch.float32 if device=='cpu' else torch.float16
kind=StableDiffusionXLInpaintPipeline if call['mode']=='edit' else StableDiffusionXLPipeline
pipeline=kind.from_pretrained(provision['weights'],local_files_only=True,use_safetensors=True,torch_dtype=dtype,variant='fp16',add_watermarker=False)
pipeline.scheduler=EulerDiscreteScheduler.from_config(pipeline.scheduler.config)
pipeline.to(device); pipeline.enable_attention_slicing(); pipeline.enable_vae_slicing()
kwargs=dict(prompt=recipe['prompt'],negative_prompt=recipe['negative_prompt'],width=recipe['width'],height=recipe['height'],num_inference_steps=recipe['steps'],guidance_scale=recipe['guidance'],generator=torch.Generator(device='cpu').manual_seed(recipe['seed']))
if call['mode']=='edit':
    source=Image.open(root/'inputs/source.png').convert('RGB'); mask=Image.open(root/'inputs/mask.png')
    assert source.size==(recipe['width'],recipe['height']) and mask.size==source.size, 'Source/mask dimensions differ'
    assert mask.mode=='L' and set(mask.getdata())=={0,255}, 'Mask must be binary grayscale with both preserved and edited pixels'
    kwargs.update(image=source,mask_image=mask,strength=call['strength'])
if device=='cuda': torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize()
if device=='mps': torch.mps.synchronize()
start=time.monotonic()
image=pipeline(**kwargs).images[0].convert('RGB')
if device=='cuda': torch.cuda.synchronize()
if device=='mps': torch.mps.synchronize()
elapsed=time.monotonic()-start
result={'inference_wall_seconds':round(elapsed,3),'device':device,'gpu_kernel_seconds':None,'gpu_measurement':'not collected','gpu_peak_allocated_bytes':torch.cuda.max_memory_allocated() if device=='cuda' else None,'outside_mask_preserved':False,'native_editability':False}
if call['mode']=='edit':
    # Explicit final pixel lock, in addition to diffusion conditioning.
    image=Image.composite(image,source,mask)
    changed=ImageChops.difference(image,source)
    preserved=Image.composite(changed,Image.new('RGB',image.size),ImageChops.invert(mask))
    assert preserved.getbbox() is None, 'Pixels outside mask changed'
    assert changed.getbbox() is not None, 'Edit produced no pixel change'
    result['outside_mask_preserved']=True
assert image.size==(recipe['width'],recipe['height'])
image.save(root/'exports/photograph.png')
(root/'engine-result.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS offline SDXL',call['mode'])
