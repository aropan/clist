def trim_on_newline(text, max_length):
    if len(text) <= max_length:
        return text
    pos = text.find('\n', -max_length)
    return text[-max_length:] if pos == -1 else text[pos + 1:]
