"""Local, species-trained AlexNet adapter. No weights are downloaded automatically."""
import os,json
from pathlib import Path

def run(payload,ctx):
    ctx.check();weights=os.environ.get('ALEXNET_WEIGHTS');labels=os.environ.get('ALEXNET_LABELS')
    if not payload.get('image'):
        payload['classification']={'status':'no_image','prediction':None};ctx.log('No image supplied');return payload
    if not weights or not labels:
        payload['classification']={'status':'not_configured','prediction':None};ctx.log('No species-trained AlexNet weights configured','warning');return payload
    import torch
    from torchvision.models import alexnet
    from torchvision.transforms import Compose,Resize,CenterCrop,ToTensor,Normalize
    from PIL import Image
    from ..db import DATA
    names=json.loads(Path(labels).read_text())
    if not isinstance(names,list) or not names or not all(isinstance(n,str) for n in names): raise ValueError('Labels must be a nonempty JSON string array')
    net=alexnet(num_classes=len(names))
    net.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True));net.eval()
    preprocess=Compose([Resize(256),CenterCrop(224),ToTensor(),Normalize([.485,.456,.406],[.229,.224,.225])])
    with Image.open(DATA/'images'/payload['image']['filename']) as image:
        tensor=preprocess(image.convert('RGB')).unsqueeze(0)
    ctx.check()
    with torch.inference_mode():
        probabilities=net(tensor).softmax(dim=1)[0];values,indices=probabilities.topk(min(3,len(names)))
    ctx.check()
    candidates=[{'label':names[i],'softmax_score':round(float(v),5)} for v,i in zip(values.tolist(),indices.tolist())]
    payload['classification']={'status':'inferred','prediction':candidates[0],'candidates':candidates,'note':'Softmax scores are not calibrated confidence. Human review required.'}
    ctx.log('AlexNet inference completed; prediction remains unverified')
    return payload
