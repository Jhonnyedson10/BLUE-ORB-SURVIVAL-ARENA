# Blue Orb Survival Arena — versão Android

## Como gerar o APK (sem instalar nada no PC)
1. Crie um repositório no GitHub e envie **todo o conteúdo desta pasta** (inclusive `.github`).
2. Abra a aba **Actions → Build APK → Run workflow** (também roda sozinho a cada push).
3. Espere ~25–40 min na primeira vez. Baixe o artefato **BlueOrb-APK** → `blueorb-2.4-...-debug.apk`.
4. No celular: permita "instalar apps desconhecidos" e abra o APK.

(Alternativa: Linux/WSL com `pip install buildozer` e `buildozer -v android debug`.)

## Controles no celular
- **Metade esquerda da tela**: joystick flutuante para MOVER (aparece onde você tocar).
- **Metade direita**: joystick flutuante para MIRAR e ATIRAR.
- Botões à direita: **AUTO** (mira/tiro automático), **ULT**, **DASH**; **II** no topo = pausa.
- Mover e mirar funcionam ao mesmo tempo (multitoque). Botão Voltar do Android = pausar/voltar.
- Menus: toque nos botões; arraste para cima/baixo para trocar a página em "Cartas".

## Ajustes
- Qualidade padrão no celular: MÉDIA (Configurações → Qualidade Gráfica → BAIXA se travar).
- Resolução lógica: `MOBILE_VH` no `main.py` (720; use 540 para aparelhos fracos).
- Saves ficam na pasta privada do app e sobrevivem a atualizações.
- Para testar o layout mobile no PC: `BLUE_ORB_MOBILE=1 python main.py`.
