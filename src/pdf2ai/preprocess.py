"""Optional cross-platform Ghostscript text outlining; never invokes Illustrator."""
from pathlib import Path
import shutil
import subprocess

from .vector import ConversionError


def outline_pdf(source: Path, output: Path, executable: str | None = None) -> None:
    command = executable or next((shutil.which(name) for name in ('gs','gswin64c','gswin32c') if shutil.which(name)), None)
    if not command:
        raise ConversionError('Text outlining requires Ghostscript. Install it or specify --ghostscript PATH.')
    args = [command, '-dSAFER', '-dBATCH', '-dNOPAUSE', '-q', '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.7', '-dNoOutputFonts', '-dAutoRotatePages=/None',
            '-sColorConversionStrategy=LeaveColorUnchanged', '-dPreserveSeparation=true',
            '-dPreserveDeviceN=true', '-dDownsampleColorImages=false',
            '-dDownsampleGrayImages=false', '-dDownsampleMonoImages=false',
            '-dPassThroughJPEGImages=true', '-dPassThroughJPXImages=true',
            f'-sOutputFile={output.resolve()}', '-f', str(source.resolve())]
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=180)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ConversionError(f'Ghostscript could not outline text: {exc}') from exc
    if result.returncode != 0 or not output.is_file():
        message = (result.stderr or result.stdout).strip()[-2000:]
        raise ConversionError(f'Ghostscript failed to outline text: {message}')
