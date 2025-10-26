![DALL·E Twiga Discord](https://github.com/user-attachments/assets/de0cc88b-b75f-43aa-850c-34c1315a5980)

<h1 align="center">🦒 Twiga: empowering Tanzanian education with AI 🦒</h1>

<div align="center">

[![GitHub License](https://img.shields.io/github/license/Tanzania-AI-Community/twiga)](https://github.com/Tanzania-AI-Community/twiga?tab=MIT-1-ov-file)
[![Discord](https://img.shields.io/discord/1260910452683178024?logo=discord&logoColor=%23f6ffff&labelColor=%234a6be4&color=%235a5a5a)](https://discord.gg/bCe2HfZY2C)
[![GitHub Issues or Pull Requests](https://img.shields.io/github/issues/Tanzania-AI-Community/twiga)](https://github.com/Tanzania-AI-Community/twiga/issues)
[![All Contributors](https://img.shields.io/github/all-contributors/Tanzania-AI-Community/twiga?color=ee8449)](#contributors)
[![Static Badge](https://img.shields.io/badge/thesis_repo-%235b5b5b?logo=github&link=https%3A%2F%2Fgithub.com%2Fjurmy24%2Ftwiga-thesis)](https://github.com/jurmy24/twiga-thesis)

</div>

Twiga is a WhatsApp chatbot designed specifically for Tanzanian teachers, and is being built by the [Tanzania AI Community](https://ai.or.tz/) and open-source contributors. It aims to enhance the educational experience for educators by providing them with access to generative AI. Using retrieval-augmented generation (RAG), Twiga can communicate with teachers in a natural way yet combine the adaptive capabilities of LLMs with the knowledge provided in the curriculum and textbooks of the Tanzanian Institute of Education (TIE). We aim to build the bot to be used for a multitude of educational applications such as generating exams, writing lesson plans, searching for textbook info, and more.

This project was awarded the [Meta Llama Impact Grant Innovation Award 2024](https://ai.meta.com/blog/llama-impact-grant-innovation-award-winners-2024/) for its use of Llama open source LLMs for social good. Read our [roadmap](https://docs.google.com/document/d/1zus2AFyglt1RJdLeqWeAJIT-uHQh6NeU9WuamzAd-0s/edit?usp=sharing) for further details on our development plans.

## 🩷 Sponsors

We would like to thank those who are sponsoring this project.

<table align="center" style="background-color: #f9f9f9; padding: 20px; border-radius: 10px;">
  <tr>
    <td align="center" style="padding: 20px;">
      <a href="https://ai.meta.com/blog/llama-impact-grant-innovation-award-winners-2024/">
        <img src="https://github.com/user-attachments/assets/b638f1e6-5a63-4406-bbc5-829341b167ab" alt="Meta" height="50">
      </a>
      <p><strong>Meta</strong><br>
      Sponsoring us through the LLaMA Impact Grant Innovation Award, allowing us to build LLM tools for social good.</p>
    </td>
    <td align="center" style="padding: 20px;">
      <a href="https://neon.tech/">
        <img src="https://github.com/user-attachments/assets/cf268032-ac06-47ed-a3d9-3bfbbe3a083e" alt="Neon" height="50">
      </a>
      <p><strong>Neon</strong><br>
      Providing database infrastructure that helps us maintain high performance.</p>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding: 20px;">
      <a href="https://modal.com/">
        <img src="data:image/svg+xml,%3csvg%20width='368'%20height='192'%20viewBox='0%200%20368%20192'%20fill='none'%20xmlns='http://www.w3.org/2000/svg'%3e%3cpath%20d='M148.873%204L183.513%2064L111.922%20188C110.492%20190.47%20107.853%20192%20104.993%20192H40.3325C38.9025%20192%2037.5325%20191.62%2036.3325%20190.93C35.1325%20190.24%2034.1226%20189.24%2033.4026%20188L1.0725%20132C-0.3575%20129.53%20-0.3575%20126.48%201.0725%20124L70.3625%204C71.0725%202.76%2072.0925%201.76001%2073.2925%201.07001C74.4925%200.380007%2075.8625%200%2077.2925%200H141.952C144.812%200%20147.453%201.53%20148.883%204H148.873ZM365.963%20124L296.672%204C295.962%202.76%20294.943%201.76001%20293.743%201.07001C292.543%200.380007%20291.173%200%20289.743%200H225.083C222.223%200%20219.583%201.53%20218.153%204L183.513%2064L255.103%20188C256.533%20190.47%20259.173%20192%20262.033%20192H326.693C328.122%20192%20329.492%20191.62%20330.693%20190.93C331.893%20190.24%20332.902%20189.24%20333.622%20188L365.953%20132C367.383%20129.53%20367.383%20126.48%20365.953%20124H365.963Z'%20fill='%2362DE61'/%3e%3cpath%20d='M109.623%2064H183.523L148.883%204C147.453%201.53%20144.813%200%20141.953%200H77.2925C75.8625%200%2074.4925%200.380007%2073.2925%201.07001L109.623%2064Z'%20fill='url(%23paint0_linear_342_139)'/%3e%3cpath%20d='M109.623%2064L73.2925%201.07001C72.0925%201.76001%2071.0825%202.76%2070.3625%204L1.0725%20124C-0.3575%20126.48%20-0.3575%20129.52%201.0725%20132L33.4026%20188C34.1126%20189.24%2035.1325%20190.24%2036.3325%20190.93L109.613%2064H109.623Z'%20fill='url(%23paint1_linear_342_139)'/%3e%3cpath%20d='M183.513%2064H109.613L36.3325%20190.93C37.5325%20191.62%2038.9025%20192%2040.3325%20192H104.993C107.853%20192%20110.492%20190.47%20111.922%20188L183.513%2064Z'%20fill='%2309AF58'/%3e%3cpath%20d='M365.963%20132C366.673%20130.76%20367.033%20129.38%20367.033%20128H294.372L258.042%20190.93C259.242%20191.62%20260.612%20192%20262.042%20192H326.703C329.563%20192%20332.202%20190.47%20333.632%20188L365.963%20132Z'%20fill='%2309AF58'/%3e%3cpath%20d='M225.083%200C223.653%200%20222.283%200.380007%20221.083%201.07001L294.362%20128H367.023C367.023%20126.62%20366.663%20125.24%20365.953%20124L296.672%204C295.242%201.53%20292.603%200%20289.743%200H225.073H225.083Z'%20fill='url(%23paint2_linear_342_139)'/%3e%3cpath%20d='M258.033%20190.93L294.362%20128L221.083%201.07001C219.883%201.76001%20218.873%202.76%20218.153%204L183.513%2064L255.103%20188C255.813%20189.24%20256.833%20190.24%20258.033%20190.93Z'%20fill='url(%23paint3_linear_342_139)'/%3e%3cdefs%3e%3clinearGradient%20id='paint0_linear_342_139'%20x1='155.803'%20y1='80'%20x2='101.003'%20y2='-14.93'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%23BFF9B4'/%3e%3cstop%20offset='1'%20stop-color='%2380EE64'/%3e%3c/linearGradient%3e%3clinearGradient%20id='paint1_linear_342_139'%20x1='8.62251'%20y1='174.93'%20x2='100.072'%20y2='16.54'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%2380EE64'/%3e%3cstop%20offset='0.18'%20stop-color='%237BEB63'/%3e%3cstop%20offset='0.36'%20stop-color='%236FE562'/%3e%3cstop%20offset='0.55'%20stop-color='%235ADA60'/%3e%3cstop%20offset='0.74'%20stop-color='%233DCA5D'/%3e%3cstop%20offset='0.93'%20stop-color='%2318B759'/%3e%3cstop%20offset='1'%20stop-color='%2309AF58'/%3e%3c/linearGradient%3e%3clinearGradient%20id='paint2_linear_342_139'%20x1='340.243'%20y1='143.46'%20x2='248.793'%20y2='-14.93'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%23BFF9B4'/%3e%3cstop%20offset='1'%20stop-color='%2380EE64'/%3e%3c/linearGradient%3e%3clinearGradient%20id='paint3_linear_342_139'%20x1='284.822'%20y1='175.47'%20x2='193.372'%20y2='17.0701'%20gradientUnits='userSpaceOnUse'%3e%3cstop%20stop-color='%2380EE64'/%3e%3cstop%20offset='0.18'%20stop-color='%237BEB63'/%3e%3cstop%20offset='0.36'%20stop-color='%236FE562'/%3e%3cstop%20offset='0.55'%20stop-color='%235ADA60'/%3e%3cstop%20offset='0.74'%20stop-color='%233DCA5D'/%3e%3cstop%20offset='0.93'%20stop-color='%2318B759'/%3e%3cstop%20offset='1'%20stop-color='%2309AF58'/%3e%3c/linearGradient%3e%3c/defs%3e%3c/svg%3e" alt="Modal" height="50">
      </a>
      <p><strong>Modal</strong><br>
      Providing cloud computing resources for LLM and OCR inference.</p>
    </td>
    <td align="center" style="padding: 20px;">
      <a href="https://kthais.com/">
        <img src="https://avatars.githubusercontent.com/u/57193069?s=200&v=4" alt="KTH AI Society" height="50">
      </a>
      <p><strong>KTH AI Society</strong><br>
      KTH students' organization that leads some development areas in Twiga.</p>
    </td>
  </tr>

</table>

## 📱 Demo

Here are a couple of screenshots. Alternatively, you can take a look at our brief [demo](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/twiga.gif).

<p align="center">
  <img src="https://github.com/user-attachments/assets/27fb128e-32f0-4265-baf8-2dc3ec69ca5f" alt="End of onboarding" width="300"/>
  <img src="https://github.com/user-attachments/assets/cd5bd256-9b48-487e-aa7b-d0efabf33e94" alt="Question generation" width="300"/>
</p>

## 🤝 Get involved

We encourage you to contribute to Twiga! There is plenty of documentation describing the current [architecture](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/ARCHITECTURE.md) of Twiga, how to [contribute](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/CONTRIBUTING.md), and how to [get started](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/GETTING_STARTED.md) in the `docs/` folder.

For further support you can join our [Discord](https://discord.gg/bCe2HfZY2C) to discuss directly with the community and stay up to date on what's happening, or you can contact us more formally using GitHub [Discussions](https://github.com/Tanzania-AI-Community/twiga/discussions).

Thank you to all the people that have contributed to Twiga so far!

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jurmy24"><img src="https://avatars.githubusercontent.com/u/21913954?v=4?s=100" width="100px;" alt="Victor Oldensand"/><br /><sub><b>Victor Oldensand</b></sub></a><br /><a href="#infra-jurmy24" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="#code-jurmy24" title="Code">💻</a> <a href="#bug-jurmy24" title="Bug reports">🐛</a> <a href="#doc-jurmy24" title="Documentation">📖</a> <a href="#design-jurmy24" title="Design">🎨</a> <a href="#example-jurmy24" title="Examples">💡</a> <a href="#eventOrganizing-jurmy24" title="Event Organizing">📋</a> <a href="#fundingFinding-jurmy24" title="Funding Finding">🔍</a> <a href="#ideas-jurmy24" title="Ideas, Planning, & Feedback">🤔</a> <a href="#maintenance-jurmy24" title="Maintenance">🚧</a> <a href="#mentoring-jurmy24" title="Mentoring">🧑‍🏫</a> <a href="#projectManagement-jurmy24" title="Project Management">📆</a> <a href="#question-jurmy24" title="Answering Questions">💬</a> <a href="#review-jurmy24" title="Reviewed Pull Requests">👀</a> <a href="#research-jurmy24" title="Research">🔬</a> <a href="#tutorial-jurmy24" title="Tutorials">✅</a> <a href="#talk-jurmy24" title="Talks">📢</a> <a href="#userTesting-jurmy24" title="User Testing">📓</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/EssaMohamedali"><img src="https://avatars.githubusercontent.com/u/50261366?v=4?s=100" width="100px;" alt="EssaMohamedali"/><br /><sub><b>EssaMohamedali</b></sub></a><br /><a href="#business-EssaMohamedali" title="Business development">💼</a> <a href="#content-EssaMohamedali" title="Content">🖋</a> <a href="#eventOrganizing-EssaMohamedali" title="Event Organizing">📋</a> <a href="#financial-EssaMohamedali" title="Financial">💵</a> <a href="#fundingFinding-EssaMohamedali" title="Funding Finding">🔍</a> <a href="#ideas-EssaMohamedali" title="Ideas, Planning, & Feedback">🤔</a> <a href="#projectManagement-EssaMohamedali" title="Project Management">📆</a> <a href="#promotion-EssaMohamedali" title="Promotion">📣</a> <a href="#talk-EssaMohamedali" title="Talks">📢</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Annagrace1704"><img src="https://avatars.githubusercontent.com/u/180529411?v=4?s=100" width="100px;" alt="Annagrace1704"/><br /><sub><b>Annagrace1704</b></sub></a><br /><a href="#content-Annagrace1704" title="Content">🖋</a> <a href="#design-Annagrace1704" title="Design">🎨</a> <a href="#promotion-Annagrace1704" title="Promotion">📣</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://book.fredygerman.com"><img src="https://avatars.githubusercontent.com/u/26197540?v=4?s=100" width="100px;" alt="Fredy Mgimba"/><br /><sub><b>Fredy Mgimba</b></sub></a><br /><a href="#code-fredygerman" title="Code">💻</a> <a href="#infra-fredygerman" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/alvaro-mazcu"><img src="https://avatars.githubusercontent.com/u/102028776?v=4?s=100" width="100px;" alt="Álvaro Mazcuñán Herreros"/><br /><sub><b>Álvaro Mazcuñán Herreros</b></sub></a><br /><a href="#code-alvaro-mazcu" title="Code">💻</a> <a href="#doc-alvaro-mazcu" title="Documentation">📖</a> <a href="#test-alvaro-mazcu" title="Tests">⚠️</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/wjunwei2001"><img src="https://avatars.githubusercontent.com/u/109643278?v=4?s=100" width="100px;" alt="Wang Junwei"/><br /><sub><b>Wang Junwei</b></sub></a><br /><a href="#code-wjunwei2001" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://iamrobzy.github.io/"><img src="https://avatars.githubusercontent.com/u/60611384?v=4?s=100" width="100px;" alt="Robert"/><br /><sub><b>Robert</b></sub></a><br /><a href="#code-iamrobzy" title="Code">💻</a> <a href="#ideas-iamrobzy" title="Ideas, Planning, & Feedback">🤔</a> <a href="#mentoring-iamrobzy" title="Mentoring">🧑‍🏫</a> <a href="#projectManagement-iamrobzy" title="Project Management">📆</a> <a href="#question-iamrobzy" title="Answering Questions">💬</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

## 📜 License

[MIT](https://github.com/Tanzania-AI-Community/twiga?tab=MIT-1-ov-file) License, Copyright 2024-present, Victor Oldensand
