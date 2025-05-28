import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  Svg: React.ComponentType<React.ComponentProps<'svg'>>;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Preserved State',
    Svg: () => null,
    description: (
      <>
        Variables and data remain intact throughout your session. Your AI assistant 
        can see errors, install packages, and continue where you left off.
      </>
    ),
  },
  {
    title: 'MCP Protocol',
    Svg: () => null,
    description: (
      <>
        Built on the Model Context Protocol, works with any MCP-compatible client 
        including Goose, Cursor, and more.
      </>
    ),
  },
  {
    title: 'Seamless Integration',
    Svg: () => null,
    description: (
      <>
        Continue your data exploration naturally. Hand off to the AI assistant at 
        any time to pick up exactly where you left off.
      </>
    ),
  },
];

function Feature({title, Svg, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center">
        <Svg className={styles.featureSvg} role="img" />
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}