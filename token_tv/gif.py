"""Small animated GIFs for the clock.

The SD_PRO is an ESP8266: one core plays the GIF and takes uploads, so the animation holds for as long as a send
takes, about 20 ms a kilobyte. Every byte saved is a shorter hold. Three things keep the bytes down, with the
same pixels:
- one palette of just the colours used, and LZW codes only as wide as it needs (5 or 6 bits, not 8);
- each frame after the first holds only the box that changed, its unchanged pixels transparent, which
  compresses to almost nothing;
- rows in order (Pillow interlaces by default, which compresses worse and gains nothing on a clock).
"""
import io
import struct

from PIL import Image, ImageChops, ImageFile


def indexed(frames, face):
    """The frames on one palette of just the colours they use."""
    colours = set()
    for frame in frames:
        colours.update(c for _, c in frame.getcolors(maxcolors=frame.width * frame.height))
    palette = sorted(colours)
    if len(palette) > 256:
        raise ValueError(f'{face} faces need at most 256 colours')
    reference = Image.new('P', (1, 1))
    reference.putpalette([v for c in palette for v in c])
    return [f.quantize(palette=reference, dither=Image.Dither.NONE) for f in frames]


def image_data(image, bits):
    """The LZW-coded pixels of one P image, codes starting `bits` wide: Pillow's own GIF writer always starts them
    at 8 bits whatever the palette, which costs about an eighth of the bytes."""
    buffer = io.BytesIO()
    try:  # Pillow's GIF encoder, as its own writer drives it, with the width the palette needs
        image.encoderconfig = (bits, False)
        ImageFile._save(image, buffer, [('gif', (0, 0) + image.size, 0, 'P')])
        return bytes([bits]) + buffer.getvalue() + b'\0'
    except (AttributeError, TypeError, ValueError, OSError):  # not on this Pillow: its public writer, 8-bit codes
        buffer = io.BytesIO()
    image.save(buffer, format='GIF', optimize=False, interlace=False)
    data = buffer.getvalue()
    at = 13 + (3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0)
    while data[at] == 0x21:  # extensions before the image
        at += 2
        while data[at]:
            at += data[at] + 1
        at += 1
    flags = data[at + 9]
    at += 10 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
    end = at + 1
    while data[end]:
        end += data[end] + 1
    return data[at:end + 1]


def encode(frames, durations):
    """A looping GIF of P frames that share one palette; `durations` in milliseconds. A frame equal to the one
    before only lengthens it."""
    palette = list(frames[0].getpalette()[:768])
    colours = len(palette) // 3
    clear = colours if colours < 256 else None  # an index of its own for 'unchanged'
    bits = max(2, (colours + (clear is not None) - 1).bit_length())
    table = palette + [0] * (3 * (1 << bits) - len(palette))
    width, height = frames[0].size
    shown, previous = [], None  # [box, pixels, centiseconds]
    for frame, ms in zip(frames, durations):
        if previous is None:
            shown.append([(0, 0, width, height), frame, ms])
        else:
            changed = ImageChops.difference(Image.frombytes('L', frame.size, previous.tobytes()),
                                            Image.frombytes('L', frame.size, frame.tobytes())).point(lambda v: 255 if v else 0)
            box = changed.getbbox()
            if box is None:
                shown[-1][2] += ms
                continue
            part = frame.crop(box)
            if clear is not None:
                part = Image.composite(part, Image.new('P', part.size, clear), changed.crop(box))
            shown.append([box, part, ms])
        previous = frame
    out = [b'GIF89a', struct.pack('<HHBBB', width, height, 0xF0 | (bits - 1), 0, 0), bytes(table),
           b'\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00']  # loop forever
    for n, (box, part, ms) in enumerate(shown):
        part = part.copy()
        part.putpalette(table)
        used = sorted(set(part.tobytes()))
        transparent = n > 0 and clear in used  # a box where every pixel changed has none
        index, flags, local, pixels = clear or 0, 0, b'', image_data(part, bits)
        small = max(2, (len(used) - 1).bit_length())
        if small < bits:  # a change in a few colours: its own short palette, if that comes out smaller
            mine = part.remap_palette(used)
            own = bytes(table[3 * i + c] for i in used for c in range(3)) + bytes(3 * ((1 << small) - len(used)))
            mine.putpalette(own)
            coded = image_data(mine, small)
            if len(own) + len(coded) < len(pixels):
                index, flags, local, pixels = used.index(clear) if transparent else 0, 0x80 | small - 1, own, coded
        out.append(struct.pack('<BBBBHBB', 0x21, 0xF9, 4, 1 << 2 | transparent, round(ms / 10), index, 0))
        out.append(struct.pack('<BHHHHB', 0x2C, box[0], box[1], box[2] - box[0], box[3] - box[1], flags) + local)
        out.append(pixels)
    out.append(b'\x3b')
    return b''.join(out)
