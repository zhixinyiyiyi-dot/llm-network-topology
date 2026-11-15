"""Compatibility entry point; uses the same v3 collector as course acceptance."""
import argparse, asyncio, sys
from pathlib import Path
from accept_course_runtime import run
if __name__ == '__main__':
 p=argparse.ArgumentParser();p.add_argument('--case-dir',type=Path,required=True);p.add_argument('--preflight',action='store_true');args=p.parse_args()
 try:sys.exit(asyncio.run(run(args)))
 except Exception as exc:print(type(exc).__name__+': '+str(exc));sys.exit(1)
