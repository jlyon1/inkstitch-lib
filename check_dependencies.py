#!/usr/bin/env python3
"""
Check if performance-critical dependencies are properly compiled

Run this on your VPS to identify missing optimizations:
    python check_dependencies.py
"""

import sys

def check_lxml():
    """Check if lxml is using compiled C extensions"""
    try:
        from lxml import etree
        # Check if using C implementation
        if hasattr(etree, 'LXML_VERSION'):
            print("✓ lxml is installed with C extensions")
            print(f"  Version: {'.'.join(map(str, etree.LXML_VERSION))}")
            return True
        else:
            print("✗ lxml is using slow Python fallback")
            print("  Install: pip install --force-reinstall lxml")
            return False
    except ImportError:
        print("✗ lxml not installed")
        print("  Install: pip install lxml")
        return False

def check_pillow():
    """Check if Pillow has optimizations enabled"""
    try:
        from PIL import Image
        import PIL
        print("✓ Pillow is installed")
        print(f"  Version: {PIL.__version__}")

        # Check for format support
        formats = []
        if hasattr(Image, 'JPEG'):
            formats.append("JPEG")
        if hasattr(Image, 'PNG'):
            formats.append("PNG")
        print(f"  Supported formats: {', '.join(formats) if formats else 'Limited'}")
        return True
    except ImportError:
        print("✗ Pillow not installed")
        print("  Install: pip install Pillow")
        return False

def check_pycairo():
    """Check if cairo is available for rendering"""
    try:
        import cairo
        print("✓ pycairo (cairo) is installed")
        print(f"  Version: {cairo.version}")
        return True
    except ImportError:
        print("⚠ pycairo not installed (optional but improves rendering)")
        print("  Install: pip install pycairo")
        return False

def check_numpy():
    """Check if numpy is using optimized BLAS"""
    try:
        import numpy as np
        print("✓ NumPy is installed")
        print(f"  Version: {np.__version__}")

        # Check BLAS configuration
        try:
            config = np.__config__.show()
            print("  BLAS/LAPACK: Configured")
        except:
            print("  BLAS/LAPACK: Unknown")
        return True
    except ImportError:
        print("⚠ NumPy not installed")
        return False

def check_system_resources():
    """Check available system resources"""
    try:
        import psutil
        cpu_count = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()

        print("\n📊 System Resources:")
        print(f"  CPU cores: {cpu_count} physical, {cpu_count_logical} logical")
        print(f"  Memory: {memory.total / (1024**3):.1f} GB total, {memory.available / (1024**3):.1f} GB available")
        print(f"  Memory usage: {memory.percent}%")

        # Recommendations
        if cpu_count <= 2:
            print("\n💡 Recommendation: Use 2 Gunicorn workers for your CPU count")
        if memory.total < 2 * (1024**3):
            print("💡 Recommendation: Consider increasing memory (current < 2GB)")
            print("   - Reduce cache size")
            print("   - Use swap space")

    except ImportError:
        print("\n⚠ psutil not installed (can't check system resources)")
        print("  Install: pip install psutil")

def main():
    print("=" * 60)
    print("InkStitch API Dependency Check")
    print("=" * 60)
    print()

    all_ok = True
    all_ok &= check_lxml()
    all_ok &= check_pillow()
    check_pycairo()  # Optional
    check_numpy()     # Optional
    check_system_resources()

    print()
    print("=" * 60)
    if all_ok:
        print("✓ All critical dependencies are properly installed")
    else:
        print("✗ Some dependencies need attention")
        print("\nTo reinstall with optimizations:")
        print("  pip install --upgrade --force-reinstall lxml")
    print("=" * 60)

if __name__ == "__main__":
    main()
