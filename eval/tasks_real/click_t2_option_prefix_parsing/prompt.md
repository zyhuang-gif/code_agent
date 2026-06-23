Click argument-string parsing regressed. Shell-style argument strings are tokenized, but the resulting argument order is wrong for ordinary words, quoted values, escaped spaces, and incomplete input, causing the targeted parser tests to fail.

Please find the root cause in the full Click source tree and restore the expected parser behavior.
