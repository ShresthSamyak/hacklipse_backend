import tomli
with open('pyproject.toml', 'rb') as f:
    config = tomli.load(f)
deps = config['tool']['poetry']['dependencies']
out = []
for k, v in deps.items():
    if k == 'python': continue
    if isinstance(v, dict):
        version = v.get('version', '*')
        version = version.replace('^', '>=')
        out.append(f"{k}{version}")
    else:
        version = v.replace('^', '>=')
        out.append(f"{k}{version}")

with open('requirements.txt', 'w') as f:
    f.write('\n'.join(out))
