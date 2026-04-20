# axiolyze
adapter between glm and vdag

## update and install 

git submodule update --init --recursive
git submodule sync --recursive
python -m venv .dev
.dev\Scripts\Activate
pip install -e ./deps/repo_vdag
pip install -e ./deps/repo_glm



