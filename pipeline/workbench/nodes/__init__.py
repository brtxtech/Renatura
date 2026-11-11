from . import chat, parsing, analysis, alexnet, model, store, response
NODES={m.__name__.split('.')[-1]:m.run for m in [chat,parsing,analysis,alexnet,model,store,response]}
