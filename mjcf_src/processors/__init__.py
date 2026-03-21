"""
Процессоры для препроцессинга URDF и постобработки MJCF.
"""

from .urdf_preprocessor import URDFPreprocessor
from .mjcf_postprocessor import MJCFPostprocessor

__all__ = ['URDFPreprocessor', 'MJCFPostprocessor']
