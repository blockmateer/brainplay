# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 plebgang

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import asyncio
import time
import uuid
import bittensor as bt
import aiohttp
import json
from game.protocol import GameSynapse
from game.utils.ruleSysPrompt import ruleSysPrompt
from game.validator.reward import get_rewards
from game.utils.uids import get_random_uids
import random
import typing
from game.utils.game import TParticipant
from game.utils.game import (
    GameState,
    Role,
    TeamColor,
    CardColor,
    CardType,
    Clue,
    ChatMessage,
)
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.

client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))


def organize_team(self, uids):
    """
    Organize the team with 4 miners randomly

    Args:
        uids (list[int]): The list of miner uids

    Returns:
        tuple[dict[str, int], dict[str, int]]: The red team and the blue team
    """
    # devide into 2 teams randomly
    team1 = {"spymaster": uids[0], "operative": uids[1]}
    team2 = {"spymaster": uids[2], "operative": uids[3]}
    return team1, team2


def resetAnimations(self, cards):
    """
    Reset the animation of the cards

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.
        cards (list[CardType]): The list of cards
    """
    for card in cards:
        card.was_recently_revealed = False


async def create_room(self, game_state: GameState):
    endpoint = f"{self.backend_base}/api/v1/rooms/create"
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "validatorKey": self.wallet.hotkey.ss58_address,
                "cards": [
                    {
                        "word": card.word,
                        "color": card.color,
                        "isRevealed": card.is_revealed,
                        "wasRecentlyRevealed": card.was_recently_revealed,
                    }
                    for card in game_state.cards
                ],
                "chatHistory": [],  # Game just started, no chat history yet
                "currentTeam": game_state.currentTeam.value,
                "currentRole": game_state.currentRole.value,
                "previousTeam": None,  # Game just started, no previous team
                "previousRole": None,  # Game just started, no previous role
                "remainingRed": game_state.remainingRed,
                "remainingBlue": game_state.remainingBlue,
                "currentClue": None,  # Game just started, no current clue
                "currentGuesses": [],  # Game just started, no guesses yet
                "gameWinner": None,  # Game just started, no winner
                "participants": [
                    {
                        "name": p.name,
                        "hotKey": p.hotkey,
                        "team": p.team.value,
                        "role": p.role.value,
                    }
                    for p in game_state.participants
                ],
            }
            headers = self.build_signed_headers()
            async with session.post(
                endpoint, json=payload, headers=headers, timeout=10
            ) as response:
                if response.status != 200:
                    response_text = await response.text()
                    bt.logging.error(
                        f"Failed to create new room: HTTP {response.status} - {response_text}"
                    )
                    return None
                else:
                    response_text = await response.text()
                    bt.logging.info(f"Room created successfully: {response_text}")
                    try:
                        return json.loads(response_text)["data"]["id"]
                    except (json.JSONDecodeError, KeyError) as e:
                        bt.logging.error(f"Failed to parse room creation response: {e}")
                        return None
    except aiohttp.ClientError as e:
        bt.logging.error(f"Network error creating room: {e}")
        return None
    except asyncio.TimeoutError:
        bt.logging.error(f"Timeout error creating room at {endpoint}")
        return None
    except Exception as e:
        bt.logging.error(f"Unexpected error creating room: {e}")
        return None


async def update_room(self, game_state: GameState, roomId):
    endpoint = f"{self.backend_base}/api/v1/rooms/{roomId}"
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "validatorKey": self.wallet.hotkey.ss58_address,
                "cards": [
                    {
                        "word": card.word,
                        "color": card.color,
                        "isRevealed": card.is_revealed,
                        "wasRecentlyRevealed": card.was_recently_revealed,
                    }
                    for card in game_state.cards
                ],
                "chatHistory": [
                    {
                        "sender": msg.sender.value,
                        "message": msg.message,
                        "team": msg.team.value,
                        "reasoning": msg.reasoning,
                        "clueText": msg.clueText,
                        "number": msg.number,
                        "guesses": msg.guesses,
                    }
                    for msg in game_state.chatHistory
                ],
                "currentTeam": game_state.currentTeam.value,
                "currentRole": game_state.currentRole.value,
                "previousTeam": (
                    game_state.previousTeam.value if game_state.previousTeam else None
                ),
                "previousRole": (
                    game_state.previousRole.value if game_state.previousRole else None
                ),
                "remainingRed": game_state.remainingRed,
                "remainingBlue": game_state.remainingBlue,
                "currentClue": (
                    {
                        "clueText": game_state.currentClue.clueText,
                        "number": game_state.currentClue.number,
                    }
                    if game_state.currentClue
                    else None
                ),
                "currentGuesses": (
                    game_state.currentGuesses if game_state.currentGuesses else []
                ),
                "gameWinner": (
                    game_state.gameWinner.value if game_state.gameWinner else None
                ),
                "participants": [
                    {
                        "name": p.name,
                        "hotKey": p.hotkey,
                        "team": p.team.value,
                        "role": p.role.value,
                    }
                    for p in game_state.participants
                ],
                # "createdAt": "2025-04-07T17:49:16.457Z"
            }
            headers = self.build_signed_headers()
            async with session.patch(
                endpoint, json=payload, headers=headers, timeout=10
            ) as response:
                if response.status != 200:
                    response_text = await response.text()
                    bt.logging.error(
                        f"Failed to update room state: HTTP {response.status} - {response_text}"
                    )
                else:
                    bt.logging.info("Room state updated successfully")
    except aiohttp.ClientError as e:
        bt.logging.error(f"Network error updating room {roomId}: {e}")
    except asyncio.TimeoutError:
        bt.logging.error(f"Timeout error updating room {roomId} at {endpoint}")
    except Exception as e:
        bt.logging.error(f"Unexpected error updating room {roomId}: {e}")


async def remove_room(self, roomId):
    # return
    endpoint = f"{self.backend_base}/api/v1/rooms/{roomId}"
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "validatorKey": self.wallet.hotkey.ss58_address,
                "roomId": roomId,
                "action": "delete_room",
            }
            headers = self.build_signed_headers()
            async with session.delete(
                endpoint, headers=headers, timeout=10
            ) as response:
                if response.status != 200:
                    response_text = await response.text()
                    bt.logging.error(
                        f"Failed to delete room: HTTP {response.status} - {response_text}"
                    )
                else:
                    bt.logging.info("Room deleted successfully")
    except aiohttp.ClientError as e:
        bt.logging.error(f"Network error deleting room {roomId}: {e}")
    except asyncio.TimeoutError:
        bt.logging.error(f"Timeout error deleting room {roomId} at {endpoint}")
    except Exception as e:
        bt.logging.error(f"Unexpected error deleting room {roomId}: {e}")


async def forward(self):
    """
    This method is invoked by the validator at each time step.

    Its main function is to query the network and evaluate the responses.

    Parameters:
        self (bittensor.neuron.Neuron): The neuron instance containing all necessary state information for the validator.

    """
    # Select 4 miners randomly and organize 2 teams
    miner_uids = await get_random_uids(self, k=self.config.neuron.sample_size)
    miner_uids = list(miner_uids)
    # Exeption handling when number of miners less than 4
    if len(miner_uids) < 4:
        return

    (red_team, blue_team) = organize_team(self, miner_uids)
    bt.logging.info(f"\033[91mRed Team: {red_team}\033[0m")
    bt.logging.info(f"\033[94mBlue Team: {blue_team}\033[0m")

    rs_uid = red_team["spymaster"]
    ro_uid = red_team["operative"]
    bs_uid = blue_team["spymaster"]
    bo_uid = blue_team["operative"]

    rs_hotkey = self.metagraph.axons[rs_uid].hotkey
    ro_hotkey = self.metagraph.axons[ro_uid].hotkey
    bs_hotkey = self.metagraph.axons[bs_uid].hotkey
    bo_hotkey = self.metagraph.axons[bo_uid].hotkey

    participants: typing.List[TParticipant] = []
    for team in [red_team, blue_team]:
        participants.append(
            TParticipant(
                name="Miner " + str(team["spymaster"]),
                hotkey=self.metagraph.axons[team["spymaster"]].hotkey,
                team=TeamColor.RED if team == red_team else TeamColor.BLUE,
                role=Role.SPYMASTER,
            )
        )
        participants.append(
            TParticipant(
                name="Miner " + str(team["operative"]),
                hotkey=self.metagraph.axons[team["operative"]].hotkey,
                team=TeamColor.RED if team == red_team else TeamColor.BLUE,
                role=Role.OPERATIVE,
            )
        )

    # * Initialize game
    game_step = 0
    started_at = time.time()
    game_state = GameState(participants=participants)
    end_reason = "completed"
    # Create new room via API call

    # ===============🤞ROOM CREATE===================
    roomId = await create_room(self, game_state)
    if roomId is None:
        bt.logging.error("Failed to create room, exiting.")
        return
    # ===============GAME LOOP=======================
    while game_state.gameWinner is None:
        # Prepare the query
        if game_state.currentRole == Role.SPYMASTER:
            cards = game_state.cards
            if game_state.currentTeam == TeamColor.RED:
                to_uid = red_team["spymaster"]
            else:
                to_uid = blue_team["spymaster"]
        else:
            # If receiver is operative, we need to send the cards without color
            # This is because the operative doesn't know the color of the cards
            cards = [
                CardType(
                    word=card.word,
                    color=card.color if card.is_revealed else None,
                    is_revealed=card.is_revealed,
                    was_recently_revealed=card.was_recently_revealed,
                )
                for card in game_state.cards
            ]
            if game_state.currentTeam == TeamColor.RED:
                to_uid = red_team["operative"]
            else:
                to_uid = blue_team["operative"]

            # Remove animation of recently revealed cards
            resetAnimations(self, game_state.cards)
        your_team = game_state.currentTeam
        your_role = game_state.currentRole
        remaining_red = game_state.remainingRed
        remaining_blue = game_state.remainingBlue
        your_clue = (
            game_state.currentClue.clueText
            if game_state.currentClue is not None
            else None
        )
        your_number = (
            game_state.currentClue.number
            if game_state.currentClue is not None
            else None
        )

        synapse = GameSynapse(
            your_team=your_team,
            your_role=your_role,
            remaining_red=remaining_red,
            remaining_blue=remaining_blue,
            your_clue=your_clue,
            your_number=your_number,
            cards=cards,
        )

        bt.logging.info(f"⏩ Sending query to miner {to_uid}")
        responses = await self.dendrite(
            # Send the query to selected miner axons in the network.
            axons=[self.metagraph.axons[to_uid]],
            # Construct a query.
            synapse=synapse,
            # All responses have the deserialize function called on them before returning.
            # You are encouraged to define your own deserialization function.
            deserialize=True,
            timeout=10,  # TODO: Update timeout limit
        )
        # TODO: handle response timeout
        if len(responses) == 0 or responses[0] is None:
            game_state.gameWinner = (
                TeamColor.RED
                if game_state.currentTeam == TeamColor.BLUE
                else TeamColor.BLUE
            )
            resetAnimations(self, game_state.cards)
            end_reason = "no_response"
            bt.logging.info(
                f"💀 No response received! Game over. Winner: {game_state.gameWinner}"
            )
            # End the game and remove from gameboard after 10 seconds
            await update_room(self, game_state, roomId)
            break

        if game_state.currentRole == Role.SPYMASTER:
            # * Get the clue and number from the responsehttps://game.shiftlayer.ai/
            clue = responses[0].clue_text
            number = responses[0].number
            reasoning = responses[0].reasoning
            game_state.currentClue = Clue(clueText=clue, number=number)
            bt.logging.info(f"Clue: {clue}, Number: {number}")
            bt.logging.info(f"Reasoning: {reasoning}")

            # * Check if the clue is valid using the ruleSysPrompt
            board_words = [
                card.word for card in game_state.cards if not card.is_revealed
            ]
            messages = []
            messages.append({"role": "system", "content": ruleSysPrompt})
            messages.append(
                {
                    "role": "user",
                    "content": f"Clue: {clue}, Number: {number}, Board Words: {board_words}",
                }
            )

            result = client.responses.create(
                model="gpt-5",
                input=messages,
                reasoning={"effort": "low"},  # Optional: control reasoning effort
            )
            result_json = json.loads(result.output_text)
            if result_json["valid"] == False:
                bt.logging.info(
                    f"❌ Invalid clue '{clue}' provided by miner {to_uid} for board words {board_words}. Reason: {result_json['reason']}"
                )
                # If the clue is invalid, the other team wins
                game_state.gameWinner = (
                    TeamColor.RED
                    if game_state.currentTeam == TeamColor.BLUE
                    else TeamColor.BLUE
                )
                resetAnimations(self, game_state.cards)
                end_reason = "invalid_clue"
                bt.logging.info(
                    f"💀 Invalid clue! Game over. Winner: {game_state.gameWinner}"
                )
                await update_room(self, game_state, roomId)
                # time.sleep(5)
                break

            game_state.chatHistory.append(
                ChatMessage(
                    sender=Role.SPYMASTER,
                    message=f"Gave clue '{clue}' with number {number}",
                    team=game_state.currentTeam,
                    clueText=clue,
                    number=number,
                    reasoning=reasoning,
                )
            )
            game_state.currentClue.clueText = clue
            game_state.currentClue.number = number

        elif game_state.currentRole == Role.OPERATIVE:
            # * Get the guessed cards from the response
            guesses = responses[0].guesses
            reasoning = responses[0].reasoning
            bt.logging.info(f"Guessed cards: {guesses}")
            bt.logging.info(f"Reasoning: {reasoning}")
            # * Update the game state
            choose_assasin = False
            for guess in guesses:
                card = next((c for c in game_state.cards if c.word == guess), None)
                if card is None or card.is_revealed:
                    bt.logging.debug(f"Invalid guess: {guess}")
                    continue
                card.is_revealed = True
                card.was_recently_revealed = True
                if card.color == "red":
                    game_state.remainingRed -= 1
                elif card.color == "blue":
                    game_state.remainingBlue -= 1
                if game_state.remainingRed == 0:
                    game_state.gameWinner = TeamColor.RED
                    resetAnimations(self, game_state.cards)
                    end_reason = "red_all_cards"
                    bt.logging.info(
                        f"🎉 All red cards found! Winner: {game_state.gameWinner}"
                    )
                    await update_room(self, game_state, roomId)
                    break
                elif game_state.remainingBlue == 0:
                    game_state.gameWinner = TeamColor.BLUE
                    resetAnimations(self, game_state.cards)
                    end_reason = "blue_all_cards"
                    bt.logging.info(
                        f"🎉 All blue cards found! Winner: {game_state.gameWinner}"
                    )
                    await update_room(self, game_state, roomId)
                    break
                if card.color == "assassin":
                    choose_assasin = True
                    game_state.gameWinner = (
                        TeamColor.RED
                        if game_state.currentTeam == TeamColor.BLUE
                        else TeamColor.BLUE
                    )
                    resetAnimations(self, game_state.cards)
                    end_reason = "assassin"
                    bt.logging.info(
                        f"💀 Assassin card found! Game over. Winner: {game_state.gameWinner}"
                    )
                    await update_room(self, game_state, roomId)
                    # time.sleep(5)
                    break
                if card.color != game_state.currentTeam.value:
                    # If the card is not of our team color, we break
                    # This is to ensure that the operative only guesses cards of their team color
                    bt.logging.info(
                        f"Card {card.word} is not of team color {game_state.currentTeam.value}, breaking."
                    )
                    break
                # if the card isn't our team color, break
                # if card.color is not game_state.currentTeam:
                #     break
            if choose_assasin or game_state.gameWinner is not None:
                break
            game_state.currentGuesses = guesses
            game_state.chatHistory.append(
                ChatMessage(
                    sender=Role.OPERATIVE,
                    message=f"Guessed cards: {', '.join(guesses)}",
                    team=game_state.currentTeam,
                    reasoning=reasoning,
                    guesses=guesses,
                )
            )

        # change the role
        game_state.previousRole = game_state.currentRole
        game_state.previousTeam = game_state.currentTeam

        if game_state.currentRole == Role.SPYMASTER:
            game_state.currentRole = Role.OPERATIVE
        else:
            game_state.currentRole = Role.SPYMASTER

            # change the team after operative moved

            if game_state.currentTeam == TeamColor.RED:
                game_state.currentTeam = TeamColor.BLUE
            else:
                game_state.currentTeam = TeamColor.RED
        game_step += 1

        await update_room(self, game_state, roomId)
        # time.sleep(2)
    # * Game over
    ended_at = time.time()
    winner_value = (
        game_state.gameWinner.value if game_state.gameWinner is not None else None
    )
    # # Adjust the scores based on responses from miners.
    rewards = get_rewards(
        self,
        winner=game_state.gameWinner.value if game_state.gameWinner else None,
        red_team=red_team,
        blue_team=blue_team,
        end_reason=end_reason,
        current_team=game_state.currentTeam,
        current_role=game_state.currentRole,
    )

    bt.logging.info(f"Scored responses: {rewards}")
    # Update the scores based on the rewards. You may want to define your own update_scores function for custom behavior.
    self.update_scores(rewards, miner_uids)

    rewards_list = rewards.tolist() if hasattr(rewards, "tolist") else list(rewards)

    def _score_at(index: int) -> float:
        return float(rewards_list[index]) if index < len(rewards_list) else 0.0

    try:
        self.score_store.record_game(
            room_id=roomId,
            rs=rs_hotkey,
            ro=ro_hotkey,
            bs=bs_hotkey,
            bo=bo_hotkey,
            winner=winner_value,
            started_at=started_at,
            ended_at=ended_at,
            score_rs=_score_at(0),
            score_ro=_score_at(1),
            score_bs=_score_at(2),
            score_bo=_score_at(3),
            reason=end_reason,
        )
        synced = await self.score_store.sync_pending()
        if synced:
            bt.logging.info(f"Synced {synced} score rows with backend.")
    except Exception as err:  # noqa: BLE001
        bt.logging.error(f"Failed to persist game score {roomId}: {err}")

    time.sleep(1)
