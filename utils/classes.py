from typing import Optional, List
from dataclasses import dataclass, field

@dataclass
class File:
    id: str = None
    url: str = None
    name: str = None
    filetype: str = None
    content: Optional[bytes] = field(default=None, repr=False)

@dataclass
class Message:
    text: Optional[str] = None
    files: Optional[List[File]] = field(default=None)

@dataclass
class ApplicationMessage(Message):
    user: Optional[str] = None
    application: Optional[str] = None