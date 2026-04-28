export type SocialCard = {
  platform: string;
  description: string;
  handle: string;
  href: string;
};

export type Paragraph = {
  text: string;
  muted?: boolean;
  italic?: boolean;
};

export const content = {
  hero: {
    name: "Skyler Seegmiller",
    headline: "Builder, writer,",
    headlineEmphasis: "operator.",
    subhead:
      "Independent operator from Salt Lake City. I ship software, run companies, and write the occasional good sentence.",
    location: "SLC · UT",
  },
  building: {
    index: "01",
    eyebrow: "Currently",
    headline: "What I'm ",
    headlineEmphasis: "building.",
    projects: [
      {
        name: "FieldBridge",
        role: "Founder, Operator",
        status: "In production",
        description:
          "Vista ERP + field-ops bridge for heavy-civil contractors. Multi-tenant SaaS born inside VanCon Inc.",
      },
      {
        name: "Pipeline OS",
        role: "Co-builder",
        status: "Public beta",
        description:
          "An honest sales operating system for small teams. Apollo + Loom + Stripe glued together with calm.",
      },
      {
        name: "Substack",
        role: "Writer",
        status: "Weekly",
        description:
          "Stoic essays on raising a son, building businesses, and the long arc of a quiet life.",
      },
    ],
  },
  connect: {
    index: "02",
    eyebrow: "Channels",
    headline: "Find me ",
    headlineEmphasis: "anywhere.",
    cards: [
      {
        platform: "Email",
        description: "The fastest way to reach me. I read everything.",
        handle: "hello@skylerseegmiller.com",
        href: "mailto:hello@skylerseegmiller.com",
      },
      {
        platform: "X",
        description: "Half-formed thoughts, screenshots, and replies in public.",
        handle: "@skylerseegmiller",
        href: "https://x.com/skylerseegmiller",
      },
      {
        platform: "LinkedIn",
        description: "For business inquiries and the occasional polished post.",
        handle: "in/skylerseegmiller",
        href: "https://www.linkedin.com/in/skylerseegmiller",
      },
      {
        platform: "GitHub",
        description: "Open-source experiments, ideas in progress, dotfiles.",
        handle: "@skylerseeg",
        href: "https://github.com/skylerseeg",
      },
    ] satisfies SocialCard[],
  },
  about: {
    index: "03",
    eyebrow: "Off the record",
    headline: "About ",
    headlineEmphasis: "me.",
    paragraphs: [
      {
        text: "I'm a father first. Most of what I build is in service of being more present with my son, Lyric, and showing him what an examined life looks like in practice.",
      },
      {
        text: "I run companies. I write code. I read Marcus Aurelius in the morning and answer support tickets at night. I think depth beats noise on a long enough timeline.",
      },
      {
        text: "If we ever meet, I'd rather talk about something you're afraid of than something you're proud of.",
        muted: true,
        italic: true,
      },
    ] satisfies Paragraph[],
  },
} as const;
