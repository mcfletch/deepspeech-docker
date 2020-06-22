"""Load rules from rule-sets on disk"""
import logging, os, ast
from .ruleregistry import rule_by_name
from .errors import MissingRules
from . import defaults
from . import transforms
from .models import Rule, null_transform
from .defaults import PHRASE_MARKER, WORD_MARKER

try:
    unicode
except NameError:
    unicode = str

log = logging.getLogger(__name__)


# TODO: allow for plugins that define their own transforms
# and actions...


def bad_text_types(text):
    if not isinstance(text, (unicode, list, tuple)):
        return 1
    if isinstance(text, (list, tuple)):
        for i, item in enumerate(text):
            if not isinstance(item, unicode):
                return 2


def text_entry_rule(match, target):
    """Create a rule from the text-entry mini-language"""
    no_space_before = target.startswith('^')
    no_space_after = target.endswith('^')
    text = ast.literal_eval(target.strip('^'))
    if bad_text_types(text):
        raise TypeError(
            match,
            text,
            "Expect python-literal syntax for unicode, bytes, list-of-unicode or tuple of unicode",
        )

    def apply_rule(match):
        """Given a match on the rule, produce modified result"""
        match = match.copy()
        result = []
        if no_space_before:
            result.append('^')
        if isinstance(text, (unicode, bytes)):
            result.append(text)
        elif isinstance(text, (list, tuple)):
            result.extend(text)
        else:
            raise TypeError()
        if no_space_after:
            result.append('^')
        return match.prefix + result + match.suffix

    return Rule(
        match=match,
        text=text,
        target=target,
        no_space_after=no_space_after,
        no_space_before=no_space_before,
        process=[apply_rule],
    )


def transform_rule(match, target):
    """Construct a transform rule for match to target"""
    no_space_before = target.startswith('^')
    no_space_after = target.endswith('^')
    try:
        transformation = rule_by_name(target.rstrip('()'))
    except KeyError:
        log.error(
            "The rule %s => %s references an unknown function", " ".join(match), target
        )
        transformation = null_transform

    phrase = match[-1] == PHRASE_MARKER
    word = match[-1] == WORD_MARKER

    def apply_rule(match):
        """Given a match, transform and return the results"""
        if phrase:
            result = transformation(match.var_phrase)
        else:
            result = transformation(match.var_words)

        return match.prefix + result + match.suffix

    return Rule(
        match=match,
        target=target,
        no_space_after=no_space_after,
        no_space_before=no_space_before,
        process=[apply_rule],
    )


def does_not_escape(base, relative):
    """Check that relative does not escape from base (return combined or raise error)"""
    base = base.rstrip('/')
    if not base:
        raise ValueError("Need a non-root base path")
    combined = os.path.abspath(os.path.normpath(os.path.join(base, relative)))
    root = os.path.abspath(os.path.normpath(base))
    if os.path.commonpath([root, combined]) != root:
        raise ValueError(
            "Path %r would escape from %s, not allowed" % (relative, base,)
        )
    return combined


def named_ruleset_file(relative):
    """Given a relative ruleset path, find rules file with that name"""
    assert relative is not None
    for source in [
        does_not_escape(defaults.CONTEXT_DIR, '%s.rules' % (relative,)),
        does_not_escape(defaults.BUILTIN_RULESETS, '%s.rules' % (relative,)),
    ]:
        if os.path.exists(source):
            return source
    log.warning('Unable to find rules-file for %s', relative)
    raise MissingRules(relative)


def format_rules(rules):
    """Format ruleset into format for storage"""
    for match, target in rules:
        yield '%s => %s' % (' '.join(match), target)


def iter_rules(name, includes=True):
    """Given rule-file name, iteratively produce all rules
    
    include -- if True, then produce rules from all included
               files as well.
    
    yields pattern, target, source-name for each rule in the
    user's rule-sets
    """
    filename = named_ruleset_file(name)
    if filename:
        command_set = open(filename, encoding='utf-8').read()
        for i, line in enumerate(command_set.splitlines()):
            line = line.strip()
            if line.startswith('#include '):
                if includes:
                    try:
                        for pattern, target, sub_name in iter_rules(line[9:].strip()):
                            yield pattern, target, sub_name
                    except MissingRules as err:
                        err.args += ('included from %s#%i' % (name, i + 1),)
                        raise
                else:
                    log.info("Includes disabeld, ignoring: %s", line)
            if (not line) or line.startswith('#'):
                continue
            try:
                pattern, target = line.split('=>', 1)
            except ValueError as err:
                log.warning("Unable to parse rule #%i: %r", i + 1, line)
                continue
            pattern = pattern.strip().split()
            target = target.strip()
            # log.debug("%s => %s", pattern, target)
            yield pattern, target, name


def load_rules(name, rules=None, includes=True):
    """load a set of commands from a named rule-set"""
    rules = rules or {}
    rule_order = []
    for pattern, target, name in iter_rules(name, includes=True):
        branch = rules
        for word in pattern:
            branch = branch.setdefault(word, {})
        if target.strip('^').endswith('()'):
            rule = transform_rule(pattern, target[:-2])
        else:
            rule = text_entry_rule(pattern, target)
        branch[None] = rule
        rule.source = name
        rule_order.append(rule)
        log.debug("Rule: %s", rule)
    return rules, rule_order
