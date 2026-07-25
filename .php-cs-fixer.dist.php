<?php

use PhpCsFixer\Runner\Parallel\ParallelConfigFactory;

$finder = PhpCsFixer\Finder::create()
    ->files()
    ->name('*.php')
    ->ignoreVCSIgnored(true)
    ->in(__DIR__ . '/legacy')
    ->exclude('libs');

return (new PhpCsFixer\Config())
    ->setParallelConfig(ParallelConfigFactory::sequential())
    ->setRiskyAllowed(false)
    ->setRules([
        '@PER-CS3x0' => true,
        'binary_operator_spaces' => ['default' => 'single_space'],
        'method_argument_space' => [
            'after_heredoc' => true,
            'on_multiline' => 'ensure_fully_multiline',
        ],
        'no_extra_blank_lines' => [
            'tokens' => [
                'attribute',
                'curly_brace_block',
                'extra',
                'parenthesis_brace_block',
                'square_brace_block',
                'use',
            ],
        ],
        'no_spaces_around_offset' => true,
        'operator_linebreak' => [
            'only_booleans' => true,
            'position' => 'beginning',
        ],
        'single_quote' => true,
        'trim_array_spaces' => true,
        'whitespace_after_comma_in_array' => ['ensure_single_space' => true],
    ])
    ->setCacheFile(__DIR__ . '/.php-cs-fixer.cache')
    ->setUsingCache(true)
    ->setFinder($finder);
