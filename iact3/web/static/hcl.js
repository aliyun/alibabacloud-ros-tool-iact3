/*
 * Custom HCL (HashiCorp Configuration Language) / Terraform syntax definition for highlight.js
 * Covers: blocks, strings, comments, numbers, keywords, functions, arrays, objects
 */
hljs.registerLanguage('hcl', function (hljs) {
    var KEYWORDS = {
        keyword:
            'resource data variable output provider module locals terraform backend ' +
            'required_providers required_version source_version ' +
            'for_each count depends_on lifecycle provider provisioner ' +
            'dynamic for in endfor endif if else endif',
        literal: 'true false null',
        built_in: 'self each local var data terraform path module'
    };

    var COMMENT = {
        variants: [
            hljs.COMMENT('#', '$'),
            hljs.COMMENT('//', '$'),
            hljs.COMMENT('/\\*', '\\*/')
        ]
    };

    var STRING = {
        className: 'string',
        variants: [
            {
                begin: /"/, end: /"/,
                contains: [
                    {
                        className: 'subst',
                        begin: /\$\{/, end: /\}/,
                        contains: [
                            hljs.C_NUMBER_MODE,
                            { className: 'variable', begin: /[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*/ }
                        ]
                    },
                    { className: 'subst', begin: /%\{/, end: /\}/ },
                    { begin: /\\./ }
                ]
            },
            {
                className: 'string',
                begin: '<<-?\\s*[A-Z_]+\\s*$',
                end: '^[A-Z_]+\\s*$',
                contains: [hljs.BACKSLASH_ESCAPE]
            }
        ]
    };

    var NUMBER = {
        className: 'number',
        variants: [
            { begin: '\\b\\d+\\.\\d+([eE][-+]?\\d+)?\\b' },
            { begin: '\\b\\d+\\b' },
            { begin: '\\b0x[0-9a-fA-F]+\\b' }
        ],
        relevance: 0
    };

    var FUNCTION_CALL = {
        className: 'function',
        begin: '\\b[a-zA-Z_]\\w*\\s*(?=\\()',
        relevance: 0
    };

    var PROPERTY = {
        className: 'attr',
        begin: '\\b[a-zA-Z_]\\w*\\s*(?==)',
        relevance: 0
    };

    var BLOCK_LABEL = {
        className: 'string',
        begin: '"[^"]*"',
        relevance: 0
    };

    var BLOCK_HEADER = {
        className: 'title',
        begin: '\\b(resource|data|variable|output|provider|module|locals|terraform|backend|required_providers|dynamic)\\b',
        relevance: 10
    };

    return {
        aliases: ['terraform', 'tf'],
        case_insensitive: false,
        keywords: KEYWORDS,
        contains: [
            COMMENT,
            STRING,
            NUMBER,
            FUNCTION_CALL,
            PROPERTY,
            BLOCK_HEADER,
            {
                className: 'symbol',
                begin: '\\b[a-zA-Z_]\\w*\\.[a-zA-Z_]\\w*([.][a-zA-Z_]\\w*)*',
                relevance: 0
            },
            {
                className: 'punctuation',
                begin: '[\\[\\]{}()=,]',
                relevance: 0
            }
        ]
    };
});
