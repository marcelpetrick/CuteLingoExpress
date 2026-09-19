"""Parse XML elements together with their original UTF-8 byte positions."""

from dataclasses import dataclass, field
import re
from xml.etree.ElementTree import Element
from xml.parsers import expat


# Expat identifies actual elements; this only finds the end of their opening tag.
TAG_END = re.compile(rb'''(?:"[^"]*"|'[^']*'|[^'">])*?>''', re.DOTALL)


@dataclass
class ElementSpan:
    """A parsed element and the boundaries needed for lossless replacement."""

    element: Element
    start: int
    open_end: int
    close_start: int = 0
    end: int = 0
    children: list = field(default_factory=list)

    def find(self, name):
        """Find a direct child by its parsed element name."""
        return next((child for child in self.children if child.element.tag == name), None)

    def iter(self, name):
        """Yield matching descendants in document order, including this element."""
        if self.element.tag == name:
            yield self
        for child in self.children:
            yield from child.iter(name)


class PositionedXml:
    """Keep structured data and replacement boundaries from the same parser."""

    def __init__(self, content):
        self.data = content.encode('utf-8')
        self.root = None
        self._stack = []
        self._parser = expat.ParserCreate('UTF-8')
        self._parser.StartElementHandler = self._start
        self._parser.EndElementHandler = self._end
        self._parser.CharacterDataHandler = self._text
        self._parser.Parse(self.data, True)

    def _start(self, name, attributes):
        start = self._parser.CurrentByteIndex
        span = ElementSpan(Element(name, attributes), start, TAG_END.match(self.data, start).end())
        if self._stack:
            self._stack[-1].children.append(span)
            self._stack[-1].element.append(span.element)
        else:
            self.root = span
        self._stack.append(span)

    def _end(self, _name):
        span = self._stack.pop()
        if self.data[span.start:span.open_end].endswith(b'/>'):
            span.close_start = span.end = span.open_end
        else:
            span.close_start = self._parser.CurrentByteIndex
            span.end = TAG_END.match(self.data, span.close_start).end()

    def _text(self, text):
        if self._stack:
            element = self._stack[-1].element
            if len(element):
                element[-1].tail = (element[-1].tail or '') + text
            else:
                element.text = (element.text or '') + text

    def iter(self, name):
        """Yield element spans in the same order as the parsed tree."""
        yield from self.root.iter(name)

    def text(self, start, end):
        """Decode an original slice using byte positions supplied by Expat."""
        return self.data[start:end].decode('utf-8')
