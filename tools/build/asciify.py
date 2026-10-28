"""Replace every non-ASCII character in the given Python files by a \\uXXXX escape (all occur inside regex or
string literals, where Python and re both read the escape)."""
import sys

BS = chr(92)
for p in sys.argv[1:]:
    s = open(p, encoding='utf-8').read()
    t = ''.join(c if ord(c) < 127 else BS + 'u%04x' % ord(c) for c in s)
    if t != s:
        open(p, 'w', encoding='utf-8', newline='\n').write(t)
        print('fixed', p)
