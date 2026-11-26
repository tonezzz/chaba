import os, sys
PACK_DIR = os.environ.get('T_PACK_DIR', os.getcwd())
NEST_ROOT = os.environ.get('T_NEST_ROOT', PACK_DIR)
ns = {'PACK_DIR': PACK_DIR, 'NEST_ROOT': NEST_ROOT}
exec(compile(open(sys.argv[1]).read(), sys.argv[1], 'exec'), ns)
