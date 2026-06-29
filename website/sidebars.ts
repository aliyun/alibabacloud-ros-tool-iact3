import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    'installation',
    'quick-start',
    'concepts',
    {
      type: 'category',
      label: 'Usage',
      link: {type: 'doc', id: 'usage'},
      items: [
        'usage/test-run',
        'usage/inspection',
        'usage/base-resources',
        'usage/stack-cleanup',
      ],
    },
    'configuration',
    'reports',
    {
      type: 'category',
      label: 'Examples',
      items: [
        'examples/ros-sleep',
        'examples/terraform-directory',
        'examples/hooks',
        'examples/github-action',
      ],
    },
    'troubleshooting',
    'developer',
  ],
};

export default sidebars;
