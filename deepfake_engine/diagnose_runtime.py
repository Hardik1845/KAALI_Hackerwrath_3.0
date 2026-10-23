"""Isolate native-library imports and a small DeepDefend inference in child processes.

Run from the project root with: python -m deepfake_engine.diagnose_runtime
This diagnostic uses only the standard library in the parent process. A native
crash in one probe will not terminate the remaining probes or the calling shell.
"""
import os
import subprocess
import sys

PROBES = {
    "PyTorch CPU operation": "import torch; print('torch', torch.__version__); torch.set_num_threads(1); print((torch.ones((128,128)) @ torch.ones((128,128))).sum().item())",
    "NumPy + SciPy operation": "import numpy as np, scipy, scipy.fftpack as fft; print('numpy', np.__version__, 'scipy', scipy.__version__); print(fft.dctn(np.ones((128,128))).shape)",
    "OpenCV + NumPy operation": "import cv2, numpy as np; print('cv2', cv2.__version__, 'CascadeClassifier', hasattr(cv2,'CascadeClassifier')); image=np.zeros((128,128,3),dtype=np.uint8); print(cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(64,64)).shape)",
    "PyTorch then OpenCV": "import torch; import cv2, numpy as np; torch.set_num_threads(1); x=np.zeros((128,128,3),dtype=np.uint8); print(torch.ones(16,16).sum().item(), cv2.resize(x,(64,64)).shape)",
    "OpenCV then PyTorch": "import cv2, numpy as np; import torch; torch.set_num_threads(1); x=np.zeros((128,128,3),dtype=np.uint8); print(cv2.resize(x,(64,64)).shape, torch.ones(16,16).sum().item())",
    "SciPy then PyTorch": "import numpy as np, scipy.fftpack as fft; import torch; torch.set_num_threads(1); print(fft.dctn(np.ones((128,128))).shape, torch.ones(16,16).sum().item())",
    "DeepDefend synthetic inference": "import numpy as np; from deepfake_engine.pipeline import DeepfakeDetector; d=DeepfakeDetector(); r=d.analyze_image(np.zeros((256,256,3),dtype=np.uint8), False); print('verdict',r.verdict,'faces',r.faces_detected)",
}

base_env = os.environ.copy()
base_env.update({"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_THREADING_LAYER": "SEQUENTIAL"})
print(f"Python: {sys.executable}")
for name, code in PROBES.items():
    print(f"\n=== {name} ===", flush=True)
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=base_env, timeout=45)
        print(f"exit code: {result.returncode}")
        if result.stdout.strip(): print(result.stdout.strip()[-2500:])
        if result.stderr.strip(): print(result.stderr.strip()[-3500:])
    except subprocess.TimeoutExpired:
        print("TIMED OUT after 45 seconds")
    except Exception as exc:
        print(f"Could not run probe: {type(exc).__name__}: {exc}")

