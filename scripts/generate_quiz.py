#!/usr/bin/env python3
"""
QuizPop daily content pipeline — runs on GitHub Actions (free tier).
Trend discovery -> topic scoring -> quiz generation (Gemini API) ->
writes quiz pages -> updates quizzes.json + sitemap.xml.

Stdlib only. Two-phase: all quizzes are generated and validated BEFORE
anything is written, so a failure never leaves a half-built site.

Env:
  GEMINI_API_KEY   required (GitHub repo secret)
  GEMINI_MODEL     default: gemini-3.5-flash
  QUIZZES_PER_DAY  default: 3
  SITE_DOMAIN      default: https://popquizdaily.site/
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root (quizpop-site contents)
API_KEY = os.environ.get("GEMINI_API_KEY", "")
PER_DAY = int(os.environ.get("QUIZZES_PER_DAY", "3"))
DOMAIN = os.environ.get("SITE_DOMAIN", "https://popquizdaily.site/").rstrip("/") + "/"

STATIC_PAGES = ["", "personality/", "trivia/", "riddles/", "trending/",
                "search/", "about/", "contact/", "privacy/", "terms/", "disclosure/"]

# ── SEO keyword targets (research 2026-10-13, 100 low-competition long-tails).
# Priority order: seasonal first (Halloween window), then GSC-proven love cluster, then rest.
# The pipeline works through these in order, skipping anything already published.
KEYWORD_TARGETS = [
    {"kw": "which last minute halloween costume are you quiz", "cluster": "trending", "angle": "Your 11th-hour costume identity"},
    {"kw": "what halloween candy are you quiz", "cluster": "trending", "angle": "Which candy matches your vibe"},
    {"kw": "which scary movie villain are you quiz", "cluster": "trending", "angle": "Your horror alter ego"},
    {"kw": "what is your biggest halloween fear quiz", "cluster": "trending", "angle": "Name your spooky weakness"},
    {"kw": "which halloween party role are you quiz", "cluster": "trending", "angle": "Host, ghost, or wallflower"},
    {"kw": "guess the horror movie by emoji quiz", "cluster": "trending", "angle": "Emoji trivia challenge"},
    {"kw": "which vampire clan are you quiz", "cluster": "trending", "angle": "Pick your bloodline"},
    {"kw": "what halloween monster are you quiz", "cluster": "trending", "angle": "Your monster match"},
    {"kw": "which kpop demon hunters character are you quiz", "cluster": "trending", "angle": "Rumi, Mira, or Zoey"},
    {"kw": "which huntr/x member are you quiz", "cluster": "trending", "angle": "Pick your hunter"},
    {"kw": "are you rumi mira or zoey quiz", "cluster": "trending", "angle": "The trio test"},
    {"kw": "kpop demon hunters trivia quiz", "cluster": "trending", "angle": "How well do you know it"},
    {"kw": "which saja boy are you quiz", "cluster": "trending", "angle": "Pick your Saja Boy"},
    {"kw": "which demon hunter weapon are you quiz", "cluster": "trending", "angle": "Blade, bow, or charm"},
    {"kw": "which roblox the hollow monster are you quiz", "cluster": "trending", "angle": "Roblox Halloween event"},
    {"kw": "steal an egg roblox quiz", "cluster": "trending", "angle": "Roblox #1 game quiz"},
    {"kw": "which adopt me halloween pet are you quiz", "cluster": "trending", "angle": "Your spooky pet match"},
    {"kw": "99 nights in the forest survival quiz", "cluster": "trending", "angle": "Can you survive"},
    {"kw": "which doors entity are you quiz", "cluster": "trending", "angle": "Roblox DOORS entity"},
    {"kw": "which dandy's world toon are you quiz", "cluster": "trending", "angle": "Pick your toon"},
    {"kw": "which wednesday addams character are you quiz", "cluster": "trending", "angle": "Nevermore sorting"},
    {"kw": "which greek god are you quiz", "cluster": "trending", "angle": "Odyssey costume tie-in"},
    {"kw": "which nightmare before christmas character are you quiz", "cluster": "trending", "angle": "Halloween meets Christmas"},
    {"kw": "which toy story 5 character are you quiz", "cluster": "trending", "angle": "New movie characters"},
    {"kw": "which f1 driver personality are you quiz", "cluster": "trending", "angle": "Costume + racing trend"},
    {"kw": "which hunger games tribute are you quiz", "cluster": "trending", "angle": "50th Hunger Games"},
    {"kw": "what hunger games district are you from quiz", "cluster": "trending", "angle": "Your district reveal"},
    {"kw": "which sunrise on the reaping character are you quiz", "cluster": "trending", "angle": "Haymitch era"},
    {"kw": "hunger games trivia quiz", "cluster": "trending", "angle": "Test your tribute knowledge"},
    {"kw": "would you survive the 50th hunger games quiz", "cluster": "trending", "angle": "Survival odds"},
    {"kw": "which quarter quell tribute are you quiz", "cluster": "trending", "angle": "Second Quarter Quell"},
    {"kw": "are you team haymitch or team snow quiz", "cluster": "trending", "angle": "Pick your side"},
    {"kw": "which ateez member are you quiz", "cluster": "trending", "angle": "ATEEZ comeback"},
    {"kw": "which txt member are you quiz", "cluster": "trending", "angle": "TXT comeback"},
    {"kw": "which nct dream member are you quiz", "cluster": "trending", "angle": "NCT Dream comeback"},
    {"kw": "kpop bias quiz 2026", "cluster": "trending", "angle": "Find your 2026 bias"},
    {"kw": "which enhypen member are you quiz", "cluster": "trending", "angle": "ENHYPEN comeback"},
    {"kw": "which stray kids member are you quiz", "cluster": "trending", "angle": "Stray Kids comeback"},
    {"kw": "which yellowjackets character are you quiz", "cluster": "trending", "angle": "Season 4"},
    {"kw": "which rings of power character are you quiz", "cluster": "trending", "angle": "Season 3"},
    {"kw": "which pride and prejudice character are you quiz", "cluster": "trending", "angle": "New adaptation"},
    {"kw": "which black doves character are you quiz", "cluster": "trending", "angle": "Season 2"},
    {"kw": "what black friday shopper are you quiz", "cluster": "trending", "angle": "Sale season personality"},
    {"kw": "are you a sale hunter or full price buyer quiz", "cluster": "trending", "angle": "Shopping style"},
    {"kw": "black friday deals personality quiz", "cluster": "trending", "angle": "Deal hunter type"},
    {"kw": "which store are you on black friday quiz", "cluster": "trending", "angle": "Your retail alter ego"},
    {"kw": "which christmas movie are you quiz", "cluster": "trending", "angle": "Your holiday film match"},
    {"kw": "what christmas cookie are you quiz", "cluster": "trending", "angle": "Cookie personality"},
    {"kw": "which christmas character are you quiz", "cluster": "trending", "angle": "Classic character match"},
    {"kw": "which reindeer are you quiz", "cluster": "trending", "angle": "Santa's team sorting"},
    {"kw": "christmas trivia quiz", "cluster": "trending", "angle": "Holiday knowledge test"},
    {"kw": "what is your christmas aesthetic quiz", "cluster": "trending", "angle": "Your festive vibe"},
    {"kw": "which santa's workshop elf are you quiz", "cluster": "trending", "angle": "Elf role reveal"},
    {"kw": "which christmas song are you quiz", "cluster": "trending", "angle": "Your carol match"},
    {"kw": "which netflix christmas movie are you quiz", "cluster": "trending", "angle": "2026 Netflix slate"},
    {"kw": "which avengers doomsday character are you quiz", "cluster": "trending", "angle": "Doomsday lineup"},
    {"kw": "are you team avengers or team doom quiz", "cluster": "trending", "angle": "Pick your side"},
    {"kw": "avengers doomsday trivia quiz", "cluster": "trending", "angle": "Marvel knowledge test"},
    {"kw": "which doctor doom variant are you quiz", "cluster": "trending", "angle": "Doom variants"},
    {"kw": "which marvel hero are you quiz", "cluster": "trending", "angle": "Hero match"},
    {"kw": "which x-men member are you quiz", "cluster": "trending", "angle": "Mutant sorting"},
    {"kw": "which dune character are you quiz", "cluster": "trending", "angle": "Arrakis sorting"},
    {"kw": "which dune house are you quiz", "cluster": "trending", "angle": "Atreides or Harkonnen"},
    {"kw": "dune trivia quiz", "cluster": "trending", "angle": "Spice knowledge test"},
    {"kw": "are you team atreides or harkonnen quiz", "cluster": "trending", "angle": "Great house loyalty"},
    {"kw": "which dune planet are you quiz", "cluster": "trending", "angle": "Your planet match"},
    {"kw": "which jumanji avatar are you quiz", "cluster": "trending", "angle": "Game avatar match"},
    {"kw": "jumanji trivia quiz", "cluster": "trending", "angle": "Jungle knowledge test"},
    {"kw": "which jumanji game piece are you quiz", "cluster": "trending", "angle": "Pick your piece"},
    {"kw": "would you survive jumanji quiz", "cluster": "trending", "angle": "Survival odds"},
    {"kw": "which hogwarts house are you 2026 quiz", "cluster": "trending", "angle": "HBO reboot era"},
    {"kw": "harry potter series trivia quiz", "cluster": "trending", "angle": "New series knowledge"},
    {"kw": "which harry potter character are you quiz", "cluster": "trending", "angle": "Character match"},
    {"kw": "which hogwarts class are you quiz", "cluster": "trending", "angle": "Class sorting"},
    {"kw": "which magical creature are you quiz", "cluster": "trending", "angle": "Creature match"},
    {"kw": "which emily in paris character are you quiz", "cluster": "trending", "angle": "Season 6"},
    {"kw": "violent night 2 trivia quiz", "cluster": "trending", "angle": "Action Christmas sequel"},
    {"kw": "which angry birds character are you quiz", "cluster": "trending", "angle": "Movie 3"},
    {"kw": "nba christmas day trivia quiz", "cluster": "trending", "angle": "Holiday hoops"},
    {"kw": "which christmas action hero are you quiz", "cluster": "trending", "angle": "Die Hard debate energy"},
    {"kw": "which macy's thanksgiving parade balloon are you quiz", "cluster": "trending", "angle": "Parade balloon match"},
    {"kw": "what are you thankful for quiz", "cluster": "trending", "angle": "Gratitude reveal"},
    {"kw": "which thanksgiving dish matches your personality quiz", "cluster": "trending", "angle": "Plate personality"},
    {"kw": "what is your 2027 word of the year quiz", "cluster": "trending", "angle": "Your 2027 theme"},
    {"kw": "new year resolutions quiz", "cluster": "trending", "angle": "Resolution style"},
    {"kw": "what will 2027 bring you quiz", "cluster": "trending", "angle": "Year-ahead reveal"},
    {"kw": "which new year celebration are you quiz", "cluster": "trending", "angle": "Party personality"},
    {"kw": "what should your 2027 goal be quiz", "cluster": "trending", "angle": "Goal finder"},
    {"kw": "which children of blood and bone character are you quiz", "cluster": "trending", "angle": "Fantasy franchise"},
    {"kw": "which magic clan are you quiz", "cluster": "trending", "angle": "Clan sorting"},
    {"kw": "children of blood and bone trivia quiz", "cluster": "trending", "angle": "Book knowledge test"},
    {"kw": "which fantasy book world do you belong in quiz", "cluster": "trending", "angle": "World match"},
    {"kw": "which nfl playoff team are you quiz", "cluster": "trending", "angle": "Playoff fandom"},
    {"kw": "nfl trivia quiz 2027", "cluster": "trending", "angle": "Football knowledge"},
    {"kw": "guess the nfl team by emoji quiz", "cluster": "trending", "angle": "Emoji challenge"},
    {"kw": "which football position are you quiz", "cluster": "trending", "angle": "Position match"},
    {"kw": "super bowl trivia quiz", "cluster": "trending", "angle": "Big game knowledge"},
    {"kw": "which super bowl snack are you quiz", "cluster": "trending", "angle": "Game day food"},
    {"kw": "valentine's day love language quiz", "cluster": "trending", "angle": "Love style"},
    {"kw": "what is your valentine's aesthetic quiz", "cluster": "trending", "angle": "Romantic vibe"},
    {"kw": "which valentine's candy are you quiz", "cluster": "trending", "angle": "Candy match"},
    {"kw": "are you a valentine or galentine quiz", "cluster": "trending", "angle": "Feb 14 style"},
    {"kw": "which super bowl halftime performer are you quiz", "cluster": "trending", "angle": "Halftime energy"},
    {"kw": "which bts arirang song are you quiz", "cluster": "trending", "angle": "BTS world tour era"},
    {"kw": "which taylor swift era are you quiz", "cluster": "trending", "angle": "Swiftie sorting"},
    {"kw": "which steal an egg pet are you quiz", "cluster": "trending", "angle": "Roblox pets"},
    {"kw": "which kpop demon hunters song are you quiz", "cluster": "trending", "angle": "Soundtrack match"},
    {"kw": "which thanksgiving food are you quiz", "cluster": "seasonal", "angle": "Which Turkey Day dish matches you"},
    {"kw": "what thanksgiving dish are you quiz", "cluster": "seasonal", "angle": "Your Thanksgiving plate personality"},
    {"kw": "which thanksgiving side dish are you quiz", "cluster": "seasonal", "angle": "Mashed potatoes or green beans"},
    {"kw": "what kind of thanksgiving host are you quiz", "cluster": "seasonal", "angle": "Your hosting style"},
    {"kw": "which thanksgiving pie are you quiz", "cluster": "seasonal", "angle": "Pumpkin, pecan, or apple"},
    {"kw": "what thanksgiving dessert are you quiz", "cluster": "seasonal", "angle": "Your sweet ending"},
    {"kw": "are you team turkey or team ham quiz", "cluster": "seasonal", "angle": "Pick your main dish loyalty"},
    {"kw": "what is your thanksgiving role quiz", "cluster": "seasonal", "angle": "Cook, cleaner, or napper"},
    {"kw": "which friends thanksgiving character are you quiz", "cluster": "seasonal", "angle": "Your Friends episode role"},
    {"kw": "what thanksgiving movie should you watch quiz", "cluster": "seasonal", "angle": "Your Turkey Day watchlist"},
    {"kw": "which thanksgiving parade balloon are you quiz", "cluster": "seasonal", "angle": "Your Macy's balloon"},
    {"kw": "what are you thankful for quiz", "cluster": "seasonal", "angle": "Discover your gratitude style"},
    {"kw": "which fall food are you quiz", "cluster": "seasonal", "angle": "Your autumn flavor"},
    {"kw": "what kind of thanksgiving guest are you quiz", "cluster": "seasonal", "angle": "Your guest reputation"},
    {"kw": "which thanksgiving tradition are you quiz", "cluster": "seasonal", "angle": "Your family ritual"},
    {"kw": "what thanksgiving leftovers are you quiz", "cluster": "seasonal", "angle": "Your day-after sandwich"},
    {"kw": "which pie flavor are you quiz", "cluster": "seasonal", "angle": "Your pie personality"},
    {"kw": "what is your thanksgiving aesthetic quiz", "cluster": "seasonal", "angle": "Your Turkey Day vibe"},
    {"kw": "which charlie brown thanksgiving character are you quiz", "cluster": "seasonal", "angle": "Your Peanuts role"},
    {"kw": "what thanksgiving appetizer are you quiz", "cluster": "seasonal", "angle": "Your pre-dinner bite"},
    {"kw": "which turkey are you quiz", "cluster": "seasonal", "angle": "Your bird personality"},
    {"kw": "what kind of gravy are you quiz", "cluster": "seasonal", "angle": "Your gravy style"},
    {"kw": "which cranberry sauce are you quiz", "cluster": "seasonal", "angle": "Jellied or whole berry"},
    {"kw": "what thanksgiving drink are you quiz", "cluster": "seasonal", "angle": "Cider, wine, or sparkling"},
    {"kw": "which black friday shopper are you quiz", "cluster": "seasonal", "angle": "Your doorbuster style"},
    {"kw": "what is your friendsgiving role quiz", "cluster": "seasonal", "angle": "Your Friendsgiving contribution"},
    {"kw": "which thanksgiving centerpiece are you quiz", "cluster": "seasonal", "angle": "Your table decor vibe"},
    {"kw": "what thanksgiving game are you quiz", "cluster": "seasonal", "angle": "Your family game pick"},
    {"kw": "which pilgrim are you quiz", "cluster": "seasonal", "angle": "Your 1621 persona"},
    {"kw": "what mashed potato style are you quiz", "cluster": "seasonal", "angle": "Creamy, chunky, or loaded"},
    {"kw": "which stuffing are you quiz", "cluster": "seasonal", "angle": "Your stuffing identity"},
    {"kw": "what thanksgiving toast are you quiz", "cluster": "seasonal", "angle": "Your dinner speech style"},
    {"kw": "which autumn candle scent are you quiz", "cluster": "seasonal", "angle": "Your fall fragrance"},
    {"kw": "what kind of pie baker are you quiz", "cluster": "seasonal", "angle": "Your baking personality"},
    {"kw": "which thanksgiving kid table are you quiz", "cluster": "seasonal", "angle": "Your kids-table energy"},
    {"kw": "what thanksgiving nap are you quiz", "cluster": "seasonal", "angle": "Your food-coma style"},
    {"kw": "which turkey trot runner are you quiz", "cluster": "seasonal", "angle": "Your race-day persona"},
    {"kw": "what is your harvest aesthetic quiz", "cluster": "seasonal", "angle": "Your autumn harvest vibe"},
    {"kw": "which cornucopia are you quiz", "cluster": "seasonal", "angle": "Your horn of plenty"},
    {"kw": "what thanksgiving meme are you quiz", "cluster": "seasonal", "angle": "Your Turkey Day meme"},
    {"kw": "which pumpkin dish are you quiz", "cluster": "seasonal", "angle": "Beyond the pie"},
    {"kw": "what fall boot are you quiz", "cluster": "seasonal", "angle": "Your autumn footwear"},
    {"kw": "which sweater weather are you quiz", "cluster": "seasonal", "angle": "Your cozy level"},
    {"kw": "what thanksgiving playlist are you quiz", "cluster": "seasonal", "angle": "Your dinner soundtrack"},
    {"kw": "which gravy boat are you quiz", "cluster": "seasonal", "angle": "Your table role"},
    {"kw": "what kind of cranberry are you quiz", "cluster": "seasonal", "angle": "Tart or sweet"},
    {"kw": "which thanksgiving float are you quiz", "cluster": "seasonal", "angle": "Your parade moment"},
    {"kw": "what pumpkin spice level are you quiz", "cluster": "seasonal", "angle": "Your PSL intensity"},
    {"kw": "which harvest moon are you quiz", "cluster": "seasonal", "angle": "Your autumn moon"},
    {"kw": "what thanksgiving scent are you quiz", "cluster": "seasonal", "angle": "Roast turkey or cinnamon"},
    {"kw": "which christmas movie are you quiz", "cluster": "seasonal", "angle": "Your holiday film match"},
    {"kw": "what christmas character are you quiz", "cluster": "seasonal", "angle": "Your Christmas persona"},
    {"kw": "which grinch character are you quiz", "cluster": "seasonal", "angle": "Whoville or Mt. Crumpit"},
    {"kw": "what kind of elf are you quiz", "cluster": "seasonal", "angle": "Your North Pole job"},
    {"kw": "which home alone character are you quiz", "cluster": "seasonal", "angle": "Your McCallister role"},
    {"kw": "which christmas song are you quiz", "cluster": "seasonal", "angle": "Your carol identity"},
    {"kw": "what is your christmas aesthetic quiz", "cluster": "seasonal", "angle": "Your holiday vibe"},
    {"kw": "which santas reindeer are you quiz", "cluster": "seasonal", "angle": "Dasher, Dancer, or Rudolph"},
    {"kw": "what christmas gift are you quiz", "cluster": "seasonal", "angle": "Your present personality"},
    {"kw": "which elf on the shelf are you quiz", "cluster": "seasonal", "angle": "Your shelf mischief level"},
    {"kw": "what kind of christmas shopper are you quiz", "cluster": "seasonal", "angle": "Your gift-buying style"},
    {"kw": "which christmas villain are you quiz", "cluster": "seasonal", "angle": "Grinch or Scrooge"},
    {"kw": "what christmas tradition are you quiz", "cluster": "seasonal", "angle": "Your family ritual"},
    {"kw": "which nutcracker character are you quiz", "cluster": "seasonal", "angle": "Your ballet role"},
    {"kw": "what hot chocolate are you quiz", "cluster": "seasonal", "angle": "Your cocoa style"},
    {"kw": "which christmas tree are you quiz", "cluster": "seasonal", "angle": "Fraser fir or tinsel"},
    {"kw": "what is your christmas love language quiz", "cluster": "seasonal", "angle": "Holiday affection style"},
    {"kw": "which rudolph character are you quiz", "cluster": "seasonal", "angle": "Your Rankin-Bass role"},
    {"kw": "what christmas cookie are you quiz", "cluster": "seasonal", "angle": "Sugar, gingerbread, or snickerdoodle"},
    {"kw": "which santa claus are you quiz", "cluster": "seasonal", "angle": "Your Santa variant"},
    {"kw": "what kind of christmas light are you quiz", "cluster": "seasonal", "angle": "Warm white or multicolor"},
    {"kw": "which christmas stocking are you quiz", "cluster": "seasonal", "angle": "What's inside yours"},
    {"kw": "what christmas breakfast are you quiz", "cluster": "seasonal", "angle": "Your morning feast"},
    {"kw": "which polar express character are you quiz", "cluster": "seasonal", "angle": "Your train seat"},
    {"kw": "what is your winter aesthetic quiz", "cluster": "seasonal", "angle": "Your cold-weather vibe"},
    {"kw": "which frosty the snowman character are you quiz", "cluster": "seasonal", "angle": "Your snow-day role"},
    {"kw": "what christmas market are you quiz", "cluster": "seasonal", "angle": "Your European market"},
    {"kw": "which gingerbread are you quiz", "cluster": "seasonal", "angle": "Your cookie self"},
    {"kw": "what kind of snowflake are you quiz", "cluster": "seasonal", "angle": "Your unique pattern"},
    {"kw": "which christmas carol are you quiz", "cluster": "seasonal", "angle": "Your Dickens character"},
    {"kw": "what christmas eve are you quiz", "cluster": "seasonal", "angle": "Your Dec 24 style"},
    {"kw": "which krampus are you quiz", "cluster": "seasonal", "angle": "Your alpine terror level"},
    {"kw": "what christmas candle scent are you quiz", "cluster": "seasonal", "angle": "Pine, cinnamon, or vanilla"},
    {"kw": "which advent calendar are you quiz", "cluster": "seasonal", "angle": "Your countdown style"},
    {"kw": "what kind of christmas morning are you quiz", "cluster": "seasonal", "angle": "Your Dec 25 energy"},
    {"kw": "which christmas ornament are you quiz", "cluster": "seasonal", "angle": "Your tree decoration"},
    {"kw": "what christmas pajamas are you quiz", "cluster": "seasonal", "angle": "Your matching set"},
    {"kw": "which santa's workshop are you quiz", "cluster": "seasonal", "angle": "Your North Pole station"},
    {"kw": "what christmas dessert are you quiz", "cluster": "seasonal", "angle": "Yule log or trifle"},
    {"kw": "which mistletoe are you quiz", "cluster": "seasonal", "angle": "Your holiday romance"},
    {"kw": "what kind of christmas card are you quiz", "cluster": "seasonal", "angle": "Your greeting style"},
    {"kw": "which christmas parade are you quiz", "cluster": "seasonal", "angle": "Your parade moment"},
    {"kw": "what christmas wreath are you quiz", "cluster": "seasonal", "angle": "Your front-door statement"},
    {"kw": "which ebenezer scrooge are you quiz", "cluster": "seasonal", "angle": "Your miser level"},
    {"kw": "what christmas star are you quiz", "cluster": "seasonal", "angle": "Your tree topper"},
    {"kw": "which christmas cracker are you quiz", "cluster": "seasonal", "angle": "Your pop and joke"},
    {"kw": "what kind of eggnog are you quiz", "cluster": "seasonal", "angle": "Spiked or classic"},
    {"kw": "which christmas village are you quiz", "cluster": "seasonal", "angle": "Your miniature world"},
    {"kw": "what christmas bell are you quiz", "cluster": "seasonal", "angle": "Your jingle"},
    {"kw": "which saint nicholas are you quiz", "cluster": "seasonal", "angle": "Your gift-giver tradition"},
    {"kw": "what christmas snow are you quiz", "cluster": "seasonal", "angle": "Flurry or blizzard"},
    {"kw": "which christmas movie villain are you quiz", "cluster": "seasonal", "angle": "Your holiday antagonist"},
    {"kw": "what kind of christmas tree topper are you quiz", "cluster": "seasonal", "angle": "Star or angel"},
    {"kw": "which christmas cookie decorator are you quiz", "cluster": "seasonal", "angle": "Your icing skills"},
    {"kw": "what christmas song lyric are you quiz", "cluster": "seasonal", "angle": "Your verse"},
    {"kw": "which white christmas character are you quiz", "cluster": "seasonal", "angle": "Your Irving Berlin role"},
    {"kw": "what christmas light display are you quiz", "cluster": "seasonal", "angle": "Your neighborhood glow"},
    {"kw": "which christmas dinner are you quiz", "cluster": "seasonal", "angle": "Your feast style"},
    {"kw": "what kind of christmas eve box are you quiz", "cluster": "seasonal", "angle": "Your Dec 24 surprise"},
    {"kw": "which christmas jumper are you quiz", "cluster": "seasonal", "angle": "Your ugly sweater"},
    {"kw": "what christmas market food are you quiz", "cluster": "seasonal", "angle": "Gluhwein or roasted nuts"},
    {"kw": "which snowman are you quiz", "cluster": "seasonal", "angle": "Your snow-day build"},
    {"kw": "what christmas wish are you quiz", "cluster": "seasonal", "angle": "Your letter to Santa"},
    {"kw": "which december birthstone are you quiz", "cluster": "seasonal", "angle": "Turquoise or tanzanite"},
    {"kw": "what kind of new year are you quiz", "cluster": "seasonal", "angle": "Your Dec 31 energy"},
    {"kw": "which vampire are you quiz", "cluster": "seasonal", "angle": "Your vampire type"},
    {"kw": "what halloween monster are you quiz", "cluster": "seasonal", "angle": "Your creature feature"},
    {"kw": "which witch hat are you quiz", "cluster": "seasonal", "angle": "Pointy, wide-brim, or crooked"},
    {"kw": "what broomstick are you quiz", "cluster": "seasonal", "angle": "Your flying style"},
    {"kw": "which potion are you quiz", "cluster": "seasonal", "angle": "Your brew"},
    {"kw": "what spellbook are you quiz", "cluster": "seasonal", "angle": "Your grimoire"},
    {"kw": "which black cat are you quiz", "cluster": "seasonal", "angle": "Your familiar energy"},
    {"kw": "what halloween night are you quiz", "cluster": "seasonal", "angle": "Your Oct 31"},
    {"kw": "which candy corn are you quiz", "cluster": "seasonal", "angle": "Love it or hate it"},
    {"kw": "what trick are you quiz", "cluster": "seasonal", "angle": "Your prank style"},
    {"kw": "which jack o lantern are you quiz", "cluster": "seasonal", "angle": "Your carved face"},
    {"kw": "what haunted hayride are you quiz", "cluster": "seasonal", "angle": "Your spooky ride"},
    {"kw": "which corn maze are you quiz", "cluster": "seasonal", "angle": "Your autumn adventure"},
    {"kw": "what apple cider are you quiz", "cluster": "seasonal", "angle": "Hot or cold"},
    {"kw": "which scarecrow are you quiz", "cluster": "seasonal", "angle": "Your field guardian"},
    {"kw": "what full moon are you quiz", "cluster": "seasonal", "angle": "Your lunar phase"},
    {"kw": "which bat are you quiz", "cluster": "seasonal", "angle": "Your nocturnal self"},
    {"kw": "what spider are you quiz", "cluster": "seasonal", "angle": "Your web weaver"},
    {"kw": "which owl are you quiz", "cluster": "seasonal", "angle": "Your night watcher"},
    {"kw": "what raven are you quiz", "cluster": "seasonal", "angle": "Nevermore"},
    {"kw": "which skeleton are you quiz", "cluster": "seasonal", "angle": "Your bones"},
    {"kw": "what mummy wrap are you quiz", "cluster": "seasonal", "angle": "Your ancient style"},
    {"kw": "which gargoyle are you quiz", "cluster": "seasonal", "angle": "Your stone guardian"},
    {"kw": "what coffin are you quiz", "cluster": "seasonal", "angle": "Your final rest"},
    {"kw": "which tombstone are you quiz", "cluster": "seasonal", "angle": "Your epitaph"},
    {"kw": "what fog are you quiz", "cluster": "seasonal", "angle": "Your mist"},
    {"kw": "which thunderstorm are you quiz", "cluster": "seasonal", "angle": "Your spooky weather"},
    {"kw": "what cackle are you quiz", "cluster": "seasonal", "angle": "Your witch laugh"},
    {"kw": "which spell ingredient are you quiz", "cluster": "seasonal", "angle": "Eye of newt or toe of frog"},
    {"kw": "what magic wand are you quiz", "cluster": "seasonal", "angle": "Your wand core"},
    {"kw": "which crystal ball are you quiz", "cluster": "seasonal", "angle": "Your visions"},
    {"kw": "what tarot deck are you quiz", "cluster": "seasonal", "angle": "Your cards"},
    {"kw": "which ouija planchette are you quiz", "cluster": "seasonal", "angle": "Your spirit board"},
    {"kw": "what seance are you quiz", "cluster": "seasonal", "angle": "Your gathering"},
    {"kw": "which exorcism are you quiz", "cluster": "seasonal", "angle": "Your ritual"},
    {"kw": "what holy water are you quiz", "cluster": "seasonal", "angle": "Your blessing"},
    {"kw": "which garlic are you quiz", "cluster": "seasonal", "angle": "Your vampire repellent"},
    {"kw": "what wooden stake are you quiz", "cluster": "seasonal", "angle": "Your slayer tool"},
    {"kw": "which silver bullet are you quiz", "cluster": "seasonal", "angle": "Your werewolf cure"},
    {"kw": "what wolfsbane are you quiz", "cluster": "seasonal", "angle": "Your moonflower"},
    {"kw": "which full moon ritual are you quiz", "cluster": "seasonal", "angle": "Your transformation"},
    {"kw": "what curse are you quiz", "cluster": "seasonal", "angle": "Your hex"},
    {"kw": "which hex are you quiz", "cluster": "seasonal", "angle": "Your spell"},
    {"kw": "what jinx are you quiz", "cluster": "seasonal", "angle": "Your bad luck"},
    {"kw": "which omen are you quiz", "cluster": "seasonal", "angle": "Your sign"},
    {"kw": "what prophecy are you quiz", "cluster": "seasonal", "angle": "Your foretelling"},
    {"kw": "which apparition are you quiz", "cluster": "seasonal", "angle": "Your ghostly form"},
    {"kw": "what poltergeist are you quiz", "cluster": "seasonal", "angle": "Your noisy haunting"},
    {"kw": "which banshee are you quiz", "cluster": "seasonal", "angle": "Your wail"},
    {"kw": "what phantom are you quiz", "cluster": "seasonal", "angle": "Your opera"},
    {"kw": "which specter are you quiz", "cluster": "seasonal", "angle": "Your haunting"},
    {"kw": "what wraith are you quiz", "cluster": "seasonal", "angle": "Your shadow"},
    {"kw": "which ghoul are you quiz", "cluster": "seasonal", "angle": "Your graveyard"},
    {"kw": "what goblin are you quiz", "cluster": "seasonal", "angle": "Your mischief"},
    {"kw": "which troll are you quiz", "cluster": "seasonal", "angle": "Your bridge"},
    {"kw": "what ogre are you quiz", "cluster": "seasonal", "angle": "Your swamp"},
    {"kw": "which demon are you quiz", "cluster": "seasonal", "angle": "Your underworld"},
    {"kw": "what angel are you quiz", "cluster": "seasonal", "angle": "Your halo"},
    {"kw": "which grim reaper are you quiz", "cluster": "seasonal", "angle": "Your scythe"},
    {"kw": "which kpop demon hunters character are you quiz", "cluster": "seasonal", "angle": "Which hero or demon are you"},
    {"kw": "which huntrix member are you quiz", "cluster": "seasonal", "angle": "Rumi, Mira, or Zoey"},
    {"kw": "which saja boys member are you quiz", "cluster": "seasonal", "angle": "Jinu and the Saja Boys"},
    {"kw": "what kpop demon hunters costume should you wear quiz", "cluster": "seasonal", "angle": "Your Huntrix Halloween look"},
    {"kw": "are you a demon or a hunter quiz", "cluster": "seasonal", "angle": "KPop Demon Hunters edition"},
    {"kw": "which mario character are you quiz", "cluster": "seasonal", "angle": "Mario, Luigi, Peach, or Bowser"},
    {"kw": "what mario costume should you wear quiz", "cluster": "seasonal", "angle": "Your Nintendo Halloween look"},
    {"kw": "which mario kart character are you quiz", "cluster": "seasonal", "angle": "Your racer personality"},
    {"kw": "what it costume should you wear quiz", "cluster": "seasonal", "angle": "Pennywise or the Losers Club"},
    {"kw": "which pennywise form are you quiz", "cluster": "seasonal", "angle": "Your Derry clown manifestation"},
    {"kw": "what halloween costume should your dog wear quiz", "cluster": "seasonal", "angle": "Find your pup's perfect costume"},
    {"kw": "what halloween costume should your cat wear quiz", "cluster": "seasonal", "angle": "Find your cat's perfect costume"},
    {"kw": "which addams family costume should you wear quiz", "cluster": "seasonal", "angle": "Wednesday, Morticia, or Gomez"},
    {"kw": "which halloween monster are you quiz", "cluster": "seasonal", "angle": "Which classic monster matches your personality"},
    {"kw": "what kind of witch are you quiz", "cluster": "seasonal", "angle": "Discover your witch type"},
    {"kw": "which horror movie character are you quiz", "cluster": "seasonal", "angle": "Which horror icon are you"},
    {"kw": "what is your halloween aesthetic quiz", "cluster": "seasonal", "angle": "Find your spooky aesthetic"},
    {"kw": "which haunted house room are you quiz", "cluster": "seasonal", "angle": "Which room of the haunted house is yours"},
    {"kw": "what spooky pet should you get quiz", "cluster": "seasonal", "angle": "Your perfect spooky pet"},
    {"kw": "which vampire clan are you quiz", "cluster": "seasonal", "angle": "Which vampire bloodline calls to you"},
    {"kw": "what halloween movie should you watch quiz", "cluster": "seasonal", "angle": "Pick your Halloween movie night"},
    {"kw": "which trick or treater are you quiz", "cluster": "seasonal", "angle": "Your trick-or-treat style"},
    {"kw": "which ghost are you quiz", "cluster": "seasonal", "angle": "What kind of ghost would you be"},
    {"kw": "what pumpkin carving are you quiz", "cluster": "seasonal", "angle": "Your jack-o-lantern personality"},
    {"kw": "which halloween dessert are you quiz", "cluster": "seasonal", "angle": "Which spooky sweet are you"},
    {"kw": "which zombie apocalypse role are you quiz", "cluster": "seasonal", "angle": "Your survival role"},
    {"kw": "what halloween party theme are you quiz", "cluster": "seasonal", "angle": "Your perfect Halloween party"},
    {"kw": "which addams family member are you quiz", "cluster": "seasonal", "angle": "Which Addams are you"},
    {"kw": "what is your halloween spirit animal quiz", "cluster": "seasonal", "angle": "Your spooky spirit animal"},
    {"kw": "which hocus pocus witch are you quiz", "cluster": "seasonal", "angle": "Which Sanderson sister are you"},
    {"kw": "what kind of ghost hunter are you quiz", "cluster": "seasonal", "angle": "Your paranormal investigator type"},
    {"kw": "which halloween decoration are you quiz", "cluster": "seasonal", "angle": "Which spooky decor matches you"},
    {"kw": "what is your halloween tarot card quiz", "cluster": "seasonal", "angle": "Your Halloween tarot reading"},
    {"kw": "which wednesday character are you quiz", "cluster": "seasonal", "angle": "Which Nevermore student are you"},
    {"kw": "what halloween spell are you quiz", "cluster": "seasonal", "angle": "Which spell is in your grimoire"},
    {"kw": "what is your trick or treat strategy quiz", "cluster": "seasonal", "angle": "Your candy-haul game plan"},
    {"kw": "which beetlejuice character are you quiz", "cluster": "seasonal", "angle": "Which Neitherworld resident are you"},
    {"kw": "what kind of scare actor are you quiz", "cluster": "seasonal", "angle": "Your haunted house scare style"},
    {"kw": "which coraline character are you quiz", "cluster": "seasonal", "angle": "Which Other World resident are you"},
    {"kw": "what halloween myth are you quiz", "cluster": "seasonal", "angle": "Which spooky legend are you"},
    {"kw": "which scooby doo villain are you quiz", "cluster": "seasonal", "angle": "Which masked villain are you"},
    {"kw": "which hotel transylvania character are you quiz", "cluster": "seasonal", "angle": "Which monster hotel guest are you"},
    {"kw": "what kind of halloween host are you quiz", "cluster": "seasonal", "angle": "Your Halloween hosting style"},
    {"kw": "what is your halloween playlist vibe quiz", "cluster": "seasonal", "angle": "Your spooky season soundtrack"},
    {"kw": "which goosebumps monster are you quiz", "cluster": "seasonal", "angle": "Which Goosebumps creature are you"},
    {"kw": "which halloweentown character are you quiz", "cluster": "seasonal", "angle": "Which Halloweentown resident are you"},
    {"kw": "which stranger things monster are you quiz", "cluster": "seasonal", "angle": "Which Upside Down creature are you"},
    {"kw": "which scream character are you quiz", "cluster": "seasonal", "angle": "Your Woodsboro role"},
    {"kw": "what is your halloween bucket list quiz", "cluster": "seasonal", "angle": "Your spooky season must-dos"},
    {"kw": "which nightmare before christmas character are you quiz", "cluster": "seasonal", "angle": "Halloween Town or Christmas Town"},
    {"kw": "what halloween candy bar are you quiz", "cluster": "seasonal", "angle": "Which chocolate bar matches you"},
    {"kw": "which haunted attraction are you quiz", "cluster": "seasonal", "angle": "Your haunted house type"},
    {"kw": "what is your halloween superpower quiz", "cluster": "seasonal", "angle": "Your spooky superpower"},
    {"kw": "which fall aesthetic are you quiz", "cluster": "seasonal", "angle": "Your autumn vibe"},
    {"kw": "what kind of pumpkin are you quiz", "cluster": "seasonal", "angle": "Your pumpkin personality"},
    {"kw": "which dracula character are you quiz", "cluster": "seasonal", "angle": "Your Transylvania role"},
    {"kw": "what is your witch name quiz", "cluster": "seasonal", "angle": "Reveal your witch name"},
    {"kw": "which ghostbusters character are you quiz", "cluster": "seasonal", "angle": "Your ghostbusting role"},
    {"kw": "what is your halloween costume era quiz", "cluster": "seasonal", "angle": "Which decade's costume style is you"},
    {"kw": "which frankenstein character are you quiz", "cluster": "seasonal", "angle": "Your gothic novel role"},
    {"kw": "what is your halloween dream job quiz", "cluster": "seasonal", "angle": "Your spooky career"},
    {"kw": "which it character are you quiz", "cluster": "seasonal", "angle": "Your Derry role"},
    {"kw": "what halloween emoji are you quiz", "cluster": "seasonal", "angle": "Your spooky emoji"},
    {"kw": "which salem witch are you quiz", "cluster": "seasonal", "angle": "Your Salem persona"},
    {"kw": "what monster high character are you quiz", "cluster": "seasonal", "angle": "Your Monster High ghoul"},
    {"kw": "which haunted doll are you quiz", "cluster": "seasonal", "angle": "Your creepy doll persona"},
    {"kw": "what is your halloween love language quiz", "cluster": "seasonal", "angle": "Spooky affection style"},
    {"kw": "which trick or treat candy are you quiz", "cluster": "seasonal", "angle": "Your candy-bowl identity"},
    {"kw": "what kind of halloween neighbor are you quiz", "cluster": "seasonal", "angle": "Your street's spooky reputation"},
    {"kw": "which paranormal investigator are you quiz", "cluster": "seasonal", "angle": "Your ghost-hunting style"},
    {"kw": "what halloween costume couple are you quiz", "cluster": "seasonal", "angle": "Your duo costume"},
    {"kw": "which scary movie final girl are you quiz", "cluster": "seasonal", "angle": "Your final-girl energy"},
    {"kw": "what is your halloween morning routine quiz", "cluster": "seasonal", "angle": "Spooky AM rituals"},
    {"kw": "which haunted mansion ghost are you quiz", "cluster": "seasonal", "angle": "Your manor haunting style"},
    {"kw": "what kind of vampire are you quiz", "cluster": "seasonal", "angle": "Classic, sparkly, or feral"},
    {"kw": "what is your gothic aesthetic quiz", "cluster": "seasonal", "angle": "Your dark aesthetic"},
    {"kw": "which pumpkin spice are you quiz", "cluster": "seasonal", "angle": "Your fall flavor"},
    {"kw": "what halloween prank are you quiz", "cluster": "seasonal", "angle": "Your trickster level"},
    {"kw": "which cryptid are you quiz", "cluster": "seasonal", "angle": "Mothman, Bigfoot, or Chupacabra"},
    {"kw": "what is your halloween villain origin story quiz", "cluster": "seasonal", "angle": "How you became the villain"},
    {"kw": "which spooky season activity are you quiz", "cluster": "seasonal", "angle": "Your October vibe"},
    {"kw": "what kind of mummy are you quiz", "cluster": "seasonal", "angle": "Your ancient curse"},
    {"kw": "which halloween mask are you quiz", "cluster": "seasonal", "angle": "Your disguise"},
    {"kw": "which witch familiar are you quiz", "cluster": "seasonal", "angle": "Black cat, owl, or toad"},
    {"kw": "what halloween town job are you quiz", "cluster": "seasonal", "angle": "Your Halloweentown occupation"},
    {"kw": "which ghost story are you quiz", "cluster": "seasonal", "angle": "Your campfire tale"},
    {"kw": "what is your halloween fear quiz", "cluster": "seasonal", "angle": "What really scares you"},
    {"kw": "which monster cereal are you quiz", "cluster": "seasonal", "angle": "Count Chocula or Franken Berry"},
    {"kw": "what kind of halloween candy giver are you quiz", "cluster": "seasonal", "angle": "Full-size bar or raisins"},
    {"kw": "which spooky netflix show are you quiz", "cluster": "seasonal", "angle": "Your binge-watch pick"},
    {"kw": "what is your halloween decade quiz", "cluster": "seasonal", "angle": "Which Halloween era is yours"},
    {"kw": "which haunted hayride role are you quiz", "cluster": "seasonal", "angle": "Your hayride character"},
    {"kw": "what halloween scent are you quiz", "cluster": "seasonal", "angle": "Pumpkin, bonfire, or autumn leaves"},
    {"kw": "which vampire diaries character are you quiz", "cluster": "seasonal", "angle": "Your Mystic Falls role"},
    {"kw": "what is your halloween party role quiz", "cluster": "seasonal", "angle": "Host, DJ, or mysterious guest"},
    {"kw": "which american horror story character are you quiz", "cluster": "seasonal", "angle": "Your AHS season role"},
    {"kw": "which halloween candy are you quiz", "cluster": "seasonal", "angle": "Which Halloween Candy Are You?"},
    {"kw": "what halloween costume should i wear quiz", "cluster": "seasonal", "angle": "What Halloween Costume Should You Wear?"},
    {"kw": "am i a witch or a vampire quiz", "cluster": "seasonal", "angle": "Am I a Witch or a Vampire?"},
    {"kw": "which horror movie villain are you quiz", "cluster": "seasonal", "angle": "Which Horror Movie Villain Are You?"},
    {"kw": "what is my spooky season vibe quiz", "cluster": "seasonal", "angle": "What's Your Spooky Season Vibe?"},
    {"kw": "which haunted house character are you quiz", "cluster": "seasonal", "angle": "Which Haunted House Character Are You?"},
    {"kw": "trick or treat personality quiz", "cluster": "seasonal", "angle": "Trick or Treat Personality"},
    {"kw": "which halloween movie character are you quiz", "cluster": "seasonal", "angle": "Which Halloween Movie Character Are You?"},
    {"kw": "what kind of ghost are you quiz", "cluster": "seasonal", "angle": "What Kind of Ghost Are You?"},
    {"kw": "zombie or vampire quiz which are you", "cluster": "seasonal", "angle": "Zombie or Vampire: Which Are You?"},
    {"kw": "which halloween decoration are you quiz", "cluster": "seasonal", "angle": "Which Halloween Decoration Are You?"},
    {"kw": "what is your spooky season job title quiz", "cluster": "seasonal", "angle": "What's Your Spooky Season Job Title?"},
    {"kw": "which fall scent are you quiz", "cluster": "seasonal", "angle": "Which Fall Scent Are You?"},
    {"kw": "pumpkin spice personality quiz", "cluster": "seasonal", "angle": "Pumpkin Spice Personality"},
    {"kw": "which autumn aesthetic are you quiz", "cluster": "seasonal", "angle": "Which Autumn Aesthetic Are You?"},
    {"kw": "cozy fall personality quiz", "cluster": "seasonal", "angle": "Cozy Fall Personality"},
    {"kw": "which thanksgiving food are you quiz", "cluster": "seasonal", "angle": "Which Thanksgiving Food Are You?"},
    {"kw": "which christmas cookie are you quiz", "cluster": "seasonal", "angle": "Which Christmas Cookie Are You?"},
    {"kw": "what is my christmas aesthetic quiz", "cluster": "seasonal", "angle": "What's Your Christmas Aesthetic?"},
    {"kw": "which christmas movie character are you quiz", "cluster": "seasonal", "angle": "Which Christmas Movie Character Are You?"},
    {"kw": "which reindeer are you quiz", "cluster": "seasonal", "angle": "Which Reindeer Are You?"},
    {"kw": "what is your elf name quiz", "cluster": "seasonal", "angle": "What Is Your Elf Name?"},
    {"kw": "which holiday are you quiz", "cluster": "seasonal", "angle": "Which Holiday Are You?"},
    {"kw": "should i dress up for halloween quiz", "cluster": "seasonal", "angle": "Should I Dress Up for Halloween?"},
    {"kw": "what should i be for halloween quiz", "cluster": "seasonal", "angle": "What Should I Be for Halloween?"},
    {"kw": "does she like me quiz", "cluster": "love", "angle": "Does She Like Me?"},
    {"kw": "does my crush like me quiz", "cluster": "love", "angle": "Does My Crush Like Me?"},
    {"kw": "am i in love or just crushing quiz", "cluster": "love", "angle": "Am I in Love or Just Crushing?"},
    {"kw": "how to know if he likes you quiz", "cluster": "love", "angle": "How to Know If He Likes You:"},
    {"kw": "is he flirting or just friendly quiz", "cluster": "love", "angle": "Is He Flirting or Just Friendly?"},
    {"kw": "am i ready for a relationship quiz", "cluster": "love", "angle": "Am I Ready for a Relationship?"},
    {"kw": "what is my attachment style quiz", "cluster": "love", "angle": "What's My Attachment Style?"},
    {"kw": "am i the red flag or the green flag quiz", "cluster": "love", "angle": "Am I the Red Flag or the Green Flag?"},
    {"kw": "am i a green flag quiz", "cluster": "love", "angle": "Am I a Green Flag?"},
    {"kw": "what type of girlfriend am i quiz", "cluster": "love", "angle": "What Type of Girlfriend Am I?"},
    {"kw": "what type of boyfriend am i quiz", "cluster": "love", "angle": "What Type of Boyfriend Am I?"},
    {"kw": "who is my soulmate initial quiz", "cluster": "love", "angle": "Who Is My Soulmate? Initial"},
    {"kw": "when will i meet my soulmate quiz", "cluster": "love", "angle": "When Will I Meet My Soulmate?"},
    {"kw": "what does my crush think of me quiz", "cluster": "love", "angle": "What Does My Crush Think of Me?"},
    {"kw": "am i over my ex quiz", "cluster": "love", "angle": "Am I Over My Ex?"},
    {"kw": "does he miss me quiz", "cluster": "love", "angle": "Does He Miss Me?"},
    {"kw": "am i in a situationship quiz", "cluster": "love", "angle": "Am I in a Situationship?"},
    {"kw": "what is my love language test for teens", "cluster": "love", "angle": "Love Language Test for Teens"},
    {"kw": "what color is my personality quiz", "cluster": "decade/aesthetic", "angle": "What Color Is Your Personality?"},
    {"kw": "pick a color get a personality quiz", "cluster": "decade/aesthetic", "angle": "Pick a Color, Get a Personality"},
    {"kw": "which princess are you quiz", "cluster": "decade/aesthetic", "angle": "Which Princess Are You?"},
    {"kw": "which villain are you quiz", "cluster": "decade/aesthetic", "angle": "Which Villain Are You?"},
    {"kw": "am i the main character quiz", "cluster": "decade/aesthetic", "angle": "Am I the Main Character?"},
    {"kw": "what is my vibe quiz", "cluster": "decade/aesthetic", "angle": "What Is My Vibe?"},
    {"kw": "what animal am i quiz", "cluster": "decade/aesthetic", "angle": "What Animal Am I?"},
    {"kw": "which bird are you quiz", "cluster": "decade/aesthetic", "angle": "Which Bird Are You?"},
    {"kw": "what is my spirit animal quiz", "cluster": "decade/aesthetic", "angle": "What's My Spirit Animal?"},
    {"kw": "am i an introvert quiz", "cluster": "decade/aesthetic", "angle": "Am I an Introvert?"},
    {"kw": "introvert or extrovert quiz", "cluster": "decade/aesthetic", "angle": "Introvert or Extrovert"},
    {"kw": "what is my birth month personality quiz", "cluster": "decade/aesthetic", "angle": "What's My Birth Month Personality?"},
    {"kw": "which greek god are you quiz", "cluster": "decade/aesthetic", "angle": "Which Greek God Are You?"},
    {"kw": "which element am i quiz fire water earth air", "cluster": "decade/aesthetic", "angle": "Which Element Am I?"},
    {"kw": "what kind of friend am i quiz", "cluster": "decade/aesthetic", "angle": "What Kind of Friend Am I?"},
    {"kw": "am i a good friend quiz", "cluster": "decade/aesthetic", "angle": "Am I a Good Friend?"},
    {"kw": "what snack are you quiz", "cluster": "food", "angle": "What Snack Are You?"},
    {"kw": "what fast food are you quiz", "cluster": "food", "angle": "What Fast Food Are You?"},
    {"kw": "which soda are you quiz", "cluster": "food", "angle": "Which Soda Are You?"},
    {"kw": "what ice cream flavor are you quiz", "cluster": "food", "angle": "What Ice Cream Flavor Are You?"},
    {"kw": "which pasta are you quiz", "cluster": "food", "angle": "Which Pasta Are You?"},
    {"kw": "what breakfast food are you quiz", "cluster": "food", "angle": "What Breakfast Food Are You?"},
    {"kw": "which candy are you quiz", "cluster": "food", "angle": "Which Candy Are You?"},
    {"kw": "what fruit are you quiz", "cluster": "food", "angle": "What Fruit Are You?"},
    {"kw": "which starbucks drink are you quiz", "cluster": "food", "angle": "Which Starbucks Drink Are You?"},
    {"kw": "which cheese are you quiz", "cluster": "food", "angle": "Which Cheese Are You?"},
    {"kw": "which coquette aesthetic are you quiz", "cluster": "decade/aesthetic", "angle": "Which Coquette Aesthetic Are You?"},
    {"kw": "am i cottagecore or dark academia quiz", "cluster": "decade/aesthetic", "angle": "Am I Cottagecore or Dark Academia?"},
    {"kw": "old money aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Old Money Aesthetic"},
    {"kw": "clean girl aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Clean Girl Aesthetic"},
    {"kw": "y2k aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Y2K Aesthetic"},
    {"kw": "grunge aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Grunge Aesthetic"},
    {"kw": "fairycore aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Fairycore Aesthetic"},
    {"kw": "downtown girl aesthetic quiz", "cluster": "decade/aesthetic", "angle": "Downtown Girl Aesthetic"},
    {"kw": "what job fits my personality quiz", "cluster": "career/money", "angle": "What Job Fits My Personality?"},
    {"kw": "am i meant to be an entrepreneur quiz", "cluster": "career/money", "angle": "Am I Meant to Be an Entrepreneur?"},
    {"kw": "which career path should i choose quiz", "cluster": "career/money", "angle": "Which Career Path Should I Choose?"},
    {"kw": "what should i study in college quiz", "cluster": "career/money", "angle": "What Should I Study in College?"},
    {"kw": "trade school or college quiz", "cluster": "career/money", "angle": "Trade School or College?"},
    {"kw": "am i a leader or follower quiz", "cluster": "career/money", "angle": "Am I a Leader or Follower?"},
    {"kw": "what is my dream job based on my personality quiz", "cluster": "career/money", "angle": "What's My Dream Job? Personality"},
    {"kw": "should i quit my job quiz", "cluster": "career/money", "angle": "Should I Quit My Job?"},
    {"kw": "2000s trivia questions and answers quiz", "cluster": "trivia", "angle": "2000s Trivia Questions"},
    {"kw": "disney trivia questions quiz", "cluster": "trivia", "angle": "Disney Trivia Questions"},
    {"kw": "friends tv show trivia quiz", "cluster": "trivia", "angle": "Friends TV Show Trivia"},
    {"kw": "80s music trivia quiz", "cluster": "trivia", "angle": "80s Music Trivia"},
    {"kw": "general knowledge quiz for teens", "cluster": "trivia", "angle": "General Knowledge for Teens"},
    {"kw": "impossible trivia questions quiz", "cluster": "trivia", "angle": "Impossible Trivia Questions"},
    {"kw": "marvel trivia quiz for beginners", "cluster": "trivia", "angle": "Marvel Trivia for Beginners"},
    {"kw": "what am i riddles for adults with answers", "cluster": "riddles", "angle": "What Am I Riddles for Adults"},
    {"kw": "tricky riddles for teens with answers", "cluster": "riddles", "angle": "Tricky Riddles for Teens"},
    {"kw": "detective riddles quiz solve the mystery", "cluster": "riddles", "angle": "Detective Riddles: Solve the Mystery"},
    {"kw": "math riddles for adults quiz", "cluster": "riddles", "angle": "Math Riddles for Adults"},
    {"kw": "funny what am i riddles quiz", "cluster": "riddles", "angle": "Funny \"What Am I\" Riddles"},
    {"kw": "which dinosaur are you quiz", "cluster": "decade/aesthetic", "angle": "Which Dinosaur Are You?"},
    {"kw": "which cartoon character are you quiz", "cluster": "decade/aesthetic", "angle": "Which Cartoon Character Are You?"},
    {"kw": "what mythical pet should i get quiz", "cluster": "decade/aesthetic", "angle": "What Mythical Pet Should You Get?"},
]

# Seasonal overrides: if today falls in a window, one quiz MUST target the seasonal keyword.
# Windows start 6-8 weeks before the holiday so Google can index in time.
SEASONAL_WINDOWS = [
    ("08-15", "10-31", {"kw": "halloween personality quiz", "cluster": "seasonal",
        "angle": "which halloween monster/character are you"}),
    ("09-15", "11-30", {"kw": "thanksgiving quiz", "cluster": "seasonal",
        "angle": "which thanksgiving food are you"}),
    ("10-15", "12-28", {"kw": "christmas personality quiz", "cluster": "seasonal",
        "angle": "which christmas movie character are you"}),
    ("11-15", "01-10", {"kw": "new year quiz", "cluster": "seasonal",
        "angle": "what will the new year bring you"}),
    ("12-20", "02-14", {"kw": "valentine's day quiz", "cluster": "seasonal",
        "angle": "what's your valentine's love style"}),
]


# ── Gemini REST call (stdlib only) ──────────────────────────────────────────
def discover_models():
    """Ask the API which models this key can actually use right now.

    Self-healing: retired or overloaded models are simply absent from the
    list, so the pipeline never again dies because a hardcoded model name
    stopped working."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    names = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            name = m.get("name", "").replace("models/", "")
            if name:
                names.append(name)
    return names


def candidate_models():
    """Preferred model first, then other flash models, then anything else."""
    preferred = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    ordered = []
    for m in [preferred] + discover_models():
        if m and m not in ordered:
            ordered.append(m)
    flash = [m for m in ordered if "flash" in m.lower()]
    rest = [m for m in ordered if m not in flash]
    return flash + rest or [preferred]


def gemini(prompt, temperature=0.9):
    if not API_KEY:
        sys.exit("ERROR: GEMINI_API_KEY is not set.")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": temperature},
    }).encode()
    last_err = None
    for model in candidate_models():
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={API_KEY}")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 400 = bad key or model rejected for this call, 404 = retired,
            # 429 = rate-limited, 5xx = overloaded → try next model, never die here
            if e.code in (400, 404, 429, 500, 502, 503):
                try:
                    detail = e.read().decode(errors="replace")[:200]
                except Exception:
                    detail = ""
                print(f"WARN: model {model} unavailable (HTTP {e.code} {detail}), trying next…",
                      flush=True)
                last_err = e
                continue
            sys.exit(f"ERROR: Gemini API call failed: {e}")
        except Exception as e:
            # Timeouts are transient (slow API, not a bad model/key) —
            # try the next model instead of killing the whole run.
            if 'timed out' in str(e).lower() or isinstance(e, TimeoutError):
                print(f"WARN: model {model} timed out, trying next…",
                      flush=True)
                last_err = e
                continue
            sys.exit(f"ERROR: Gemini API call failed: {e}")
        print(f"INFO: using Gemini model {model}", flush=True)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            sys.exit(f"ERROR: unexpected Gemini response: {str(data)[:300]}")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # One malformed response must not kill a 25-quiz run:
            # try the next model instead of dying here.
            print(f"WARN: model {model} returned invalid JSON, trying next…",
                  flush=True)
            last_err = ValueError(f"invalid JSON from {model}: {text[:200]}")
            continue
    sys.exit(f"ERROR: all Gemini models failed, last error: {last_err}")


# ── Prompts ─────────────────────────────────────────────────────────────────
def trend_prompt():
    return f"""You are a US social-trend researcher for a family-friendly quiz website. Today's date: {date.today().isoformat()}.
Return a JSON array of 10 topics trending in the last 48 hours in US TikTok/YouTube/pop culture that could become a fun quiz, riddle set, or trivia quiz.
Each item: {{"topic": "...", "evidence": "why it's trending", "angle": "quiz concept in 12 words", "format": "personality|trivia|riddle"}}.
EXCLUDE: politics, elections, tragedies, disasters, health/medical claims, misinformation-prone topics, hateful content.
Return ONLY the JSON array."""


def score_prompt(topics, published, n):
    return f"""You score quiz topics for a US mobile audience (18-44). Already published titles (do NOT repeat or closely duplicate): {published}.
Topics: {json.dumps(topics)}
Score each 1-10 on: us_appeal, click_reveal (urge to see result), video_ability (works as a 20s vertical video), evergreen_reuse.
Return a JSON array of the TOP {n} as {{"topic": "...", "format": "personality|trivia|riddle", "quiz_concept": "one-line quiz concept", "total": <sum of the 4 scores>}} sorted by total desc. Return ONLY the JSON array."""


def gen_prompt(concept, fmt, target_kw=None):
    if fmt == "personality":
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "scores": [0-40, 0-40, 0-40, 0-40]}'
    else:
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "correct": 0-3}'
    kw_line = (f"TARGET KEYWORD (US search): \"{target_kw}\" — the quiz title, seo_title and meta_description "
               f"must target this exact phrase; the seo_intro must answer it.\n" if target_kw else "")
    return f"""You write original, family-friendly quizzes for QuizPop (US audience, grade-6 reading level).
Concept: {concept} | Format: {fmt}
{kw_line}Return ONLY this JSON object (no markdown, no commentary):
{{
 "title": "catchy title, max 60 chars",
 "slug": "url-slug-lowercase-hyphens",
 "hook": "one-line hook shown under the H1",
 "category": "personality|trivia|riddles",
 "seo_intro": "unique 150-200 word intro about this quiz topic",
 "tags": ["5", "short", "keywords", "us", "quiz"],
 "questions": [ exactly 6 items, each {q_spec} ],
 "results": [ exactly 3 items: {{"title": "...", "description": "40-80 words"}} ],
 "seo_title": "max 50 chars (site appends — QuizPop, keep total under 60)",
 "meta_description": "max 155 chars",
 "faq": [ exactly 3 items: {{"q": "a real 'people also ask' style question about this quiz topic", "a": "helpful 1-2 sentence answer, 40-60 words"}} ]
}}
Rules: 100% original wording (never copy existing quizzes); trivia/riddle answers must be well-established facts with exactly one correct option; personality results are fun, varied descriptions; NO medical/psychological diagnosis claims; NO politics/tragedy/health content; seo_title should contain the target keyword phrase naturally; the first FAQ question should directly answer the target keyword query."""


# ── Validation & normalization ──────────────────────────────────────────────
def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "quiz"


def thirds(results, max_score):
    """Fallback: split score range into equal thirds."""
    bounds = [(0, int(max_score * 0.4)),
              (int(max_score * 0.4) + 1, int(max_score * 0.79)),
              (int(max_score * 0.79) + 1, max_score)]
    out = []
    for r, (lo, hi) in zip(results, bounds):
        out.append({"min": lo, "max": hi, "t": r["title"], "d": r["description"]})
    return out


def normalize_quiz(q):
    """Validate + convert to the quiz.js score contract. Returns quiz dict or None."""
    try:
        fmt_trivia = "correct" in q["questions"][0]
        n = len(q["questions"])
        if not (5 <= n <= 8):
            return None
        questions = []
        for item in q["questions"]:
            opts = item["options"]
            if len(opts) != 4 or not all(isinstance(o, str) and o.strip() for o in opts):
                return None
            if fmt_trivia:
                ci = int(item["correct"])
                if not (0 <= ci <= 3):
                    return None
                scores = [100 if i == ci else 0 for i in range(4)]
            else:
                scores = [max(0, min(40, int(s))) for s in item["scores"]]
                if len(scores) != 4:
                    return None
            questions.append({"q": item["q"], "o": opts, "s": scores})
        max_score = n * (100 if fmt_trivia else 40)
        if len(q["results"]) != 3:
            return None
        results = thirds(q["results"], max_score)
        return {
            "title": q["title"][:80], "slug": slugify(q.get("slug") or q["title"]),
            "hook": q["hook"], "category": q["category"],
            "seo_intro": q["seo_intro"], "tags": q["tags"][:6],
            "questions": questions, "results": results,
            "seo_title": q["seo_title"][:70], "meta_description": q["meta_description"][:160],
            "faq": [{"q": str(i.get("q", ""))[:200], "a": str(i.get("a", ""))[:400]}
                    for i in (q.get("faq") or [])[:3]
                    if isinstance(i, dict) and i.get("q") and i.get("a")],
        }
    except (KeyError, TypeError, ValueError):
        return None


# ── Rendering ───────────────────────────────────────────────────────────────
def render_page(q, related):
    tpl = (ROOT / "scripts" / "quiz_template.html").read_text()
    rel_html = "".join(
        f'<a href="/quiz/{r["slug"]}/">{html.escape(r["title"])}</a>' for r in related[:12]
    ) or '<div class="soon">More quizzes dropping daily<br><span class="soon-badge">Stay tuned</span></div>'
    page = tpl.replace("__SEO_TITLE__", html.escape(q["seo_title"], quote=True))
    page = page.replace("__META_DESCRIPTION__", html.escape(q["meta_description"], quote=True))
    page = page.replace("__CANONICAL_URL__", f"{DOMAIN}quiz/{q['slug']}/")
    page = page.replace("__H1__", html.escape(q["title"]))
    page = page.replace("__HOOK__", html.escape(q["hook"]))
    page = page.replace("__SEO_INTRO__", html.escape(q["seo_intro"]))
    page = page.replace("__RELATED_HTML__", rel_html)
    page = page.replace("__QUIZ_DATA_JSON__",
                        json.dumps({"questions": q["questions"], "results": q["results"]},
                                   ensure_ascii=False))
    # FAQ: visible PAA answers + FAQPage schema
    faq_items = q.get("faq") or []
    if faq_items:
        faq_html = "".join(
            f'<p><strong>{html.escape(i["q"])}</strong> {html.escape(i["a"])}</p>'
            for i in faq_items)
        schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": i["q"],
             "acceptedAnswer": {"@type": "Answer", "text": i["a"]}} for i in faq_items]}
        faq_block = faq_html + ('<script type="application/ld+json">' +
                                json.dumps(schema, ensure_ascii=False) + '</script>')
    else:
        faq_block = ""
    page = page.replace("__FAQ_BLOCK__", faq_block)
    return page


def write_sitemap(quizzes):
    urls = [DOMAIN + p for p in STATIC_PAGES]
    urls += [DOMAIN + f"quiz/{z['slug']}/" for z in quizzes]
    items = "\n".join(f'  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>'
                      for u in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n</urlset>\n")


def in_window(start, end, today=None):
    """MM-DD window check, handles year wraparound (e.g. 12-20 -> 01-10)."""
    today = today or date.today()
    mmdd = today.strftime("%m-%d")
    if start <= end:
        return start <= mmdd <= end
    return mmdd >= start or mmdd <= end


def kw_already_covered(kw, published_slugs):
    """True if this keyword's topic is already published.
    Matches on the slug form, not just the first word (the old first-word
    check wrongly skipped ~80% of fresh keywords)."""
    slug = re.sub(r'[^a-z0-9]+', '-', kw.lower()).strip('-')
    slug_no_quiz = re.sub(r'-quiz$', '', slug)
    for s in published_slugs:
        s = s.lower()
        if slug in s or slug_no_quiz in s or s in slug:
            return True
    return False


def pick_concepts(published_slugs, published_titles, n):
    """Return n quiz concepts: seasonal override first, then keyword targets,
    then fall back to trend discovery. Each item: (concept, format, target_kw)."""
    concepts = []
    covered = " ".join(published_slugs + published_titles).lower()

    # 1. seasonal override
    for start, end, target in SEASONAL_WINDOWS:
        if in_window(start, end):
            if not kw_already_covered(target["kw"], published_slugs):
                concepts.append((target["angle"], "personality", target["kw"]))
                covered += " " + target["kw"]
            break

    # 2. keyword targets in priority order
    for target in KEYWORD_TARGETS:
        if len(concepts) >= n:
            break
        if kw_already_covered(target["kw"], published_slugs):
            continue
        fmt = "personality"
        if target["cluster"] in ("trivia",):
            fmt = "trivia"
        elif target["cluster"] in ("riddles",):
            fmt = "riddle"
        concepts.append((target["angle"], fmt, target["kw"]))
        covered += " " + target["kw"]

    # 3. trend discovery fills any remaining slots
    if len(concepts) < n:
        print(f"Step 1/3: discovering trends ({n - len(concepts)} slots)…")
        topics = gemini(trend_prompt())
        picks = gemini(score_prompt(topics, published_titles, n - len(concepts)))
        for p in picks:
            concepts.append((p["quiz_concept"], p.get("format", "personality"), None))
    else:
        print("Step 1/3: keyword targets cover all slots — skipping trend discovery.")
    return concepts


# ── Main ────────────────────────────────────────────────────────────────────
INDEXNOW_KEY = "f0c0a7951f4a18371a3f43156912c48e"

def indexnow_ping(urls):
    """Notify Bing/Yandex/etc via IndexNow that URLs changed. Best-effort."""
    if not urls:
        return
    body = json.dumps({
        "host": "popquizdaily.site",
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://popquizdaily.site/{INDEXNOW_KEY}.txt",
        "urlList": urls[:10000],
    }).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow.json",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"INFO: IndexNow pinged {len(urls)} urls (HTTP {r.status})", flush=True)
    except Exception as e:
        print(f"WARN: IndexNow ping failed: {e}", flush=True)


def main():
    quizzes_path = ROOT / "quizzes.json"
    quizzes = json.loads(quizzes_path.read_text()) if quizzes_path.exists() else []
    existing_slugs = {z["slug"] for z in quizzes}
    published = [z["title"] for z in quizzes]
    published_slugs = [z["slug"] for z in quizzes]

    concepts = pick_concepts(published_slugs, published, PER_DAY)

    print("Step 2/3: generating quizzes…")
    new_quizzes = []
    for concept, fmt, target_kw in concepts:
        raw = gemini(gen_prompt(concept, fmt, target_kw), temperature=1.0)
        q = normalize_quiz(raw)
        if not q:
            print(f"  SKIP (failed validation): {concept[:60]}")
            continue
        base, i = q["slug"], 2
        while q["slug"] in existing_slugs:
            q["slug"] = f"{base}-{i}"
            i += 1
        existing_slugs.add(q["slug"])
        new_quizzes.append(q)
        print(f"  OK: {q['title']}  (/quiz/{q['slug']}/)")

    if not new_quizzes:
        sys.exit("ERROR: no valid quizzes generated — nothing written.")

    # ── write phase (only reached if everything validated) ──
    for q in new_quizzes:
        pool = [z for z in quizzes if z["slug"] != q["slug"]]
        same = [z for z in pool if z.get("category") == q.get("category")]
        rest = [z for z in pool if z.get("category") != q.get("category")]
        related = (same + rest)[:12]
        page = render_page(q, related)
        outdir = ROOT / "quiz" / q["slug"]
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "index.html").write_text(page)
        quizzes.append({
            "slug": q["slug"], "title": q["title"], "category": q["category"],
            "tags": q["tags"], "description": q["meta_description"],
            "url": f"/quiz/{q['slug']}/", "questions_count": len(q["questions"]),
        })
    quizzes_path.write_text(json.dumps(quizzes, indent=2, ensure_ascii=False))
    write_sitemap(quizzes)
    print(f"DONE: {len(new_quizzes)} quizzes written.")
    # notify search engines instantly (Bing/Yandex via IndexNow)
    new_urls = [f"https://popquizdaily.site/quiz/{q['slug']}/" for q in new_quizzes]
    indexnow_ping(new_urls)


if __name__ == "__main__":
    main()
