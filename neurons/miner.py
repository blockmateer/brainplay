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

import time
import typing
import json
import ast
import numpy as np
import requests
import bittensor as bt
import os
from dotenv import load_dotenv
import game
from game.utils.spySysPrompt import spySysPrompt
from game.utils.opSysPrompt import opSysPrompt

# Bittensor Miner Template:
from game.protocol import GameSynapse, GameSynapseOutput, Ping

from openai import OpenAI
from openai import (
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)

# import base miner class which takes care of most of the boilerplate
from game.base.miner import BaseMinerNeuron

load_dotenv()

CHUTES_API_KEY = "cpk_6ba4d8f9a5f847b0a4bbd1ceeaca30d2.68ade38bc6b258d29800598adc1afb18.k84L4qSucDufPwQY5jCY3Kk1xR20muwe"
CHUTES_BASE_URL= "https://llm.chutes.ai/v1"


class Miner(BaseMinerNeuron):
    """
    Your miner neuron class. You should use this class to define your miner's behavior. In particular, you should replace the forward function with your own logic. You may also want to override the blacklist and priority functions according to your needs.

    This class inherits from the BaseMinerNeuron class, which in turn inherits from BaseNeuron. The BaseNeuron class takes care of routine tasks such as setting up wallet, subtensor, metagraph, logging directory, parsing config, etc. You can override any of the methods in BaseNeuron if you need to customize the behavior.

    This class provides reasonable default behavior for a miner such as blacklisting unrecognized hotkeys, prioritizing requests based on stake, and forwarding requests to the forward function. If you need to define custom
    """

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        if not self.check_openai_key():
            raise ValueError("Invalid OPENAI_KEY environment variable.")
        self.axon.attach(
            forward_fn=self.pong,
            blacklist_fn=self.blacklist_ping,
        )

    def make_request(self, model, messages, temperature):
        try:
            headers = {
                "Authorization": f"Bearer {CHUTES_API_KEY}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": model,
                "messages":[{"role": msg.role, "content": msg.content} for msg in messages],
                "stream": False,
                "max_tokens": 64000,
                "temperature": temperature,
            }

            resp = requests.post(CHUTES_BASE_URL+"/chat/completions", headers=headers, json=payload, timeout=600)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            print(content)

            return content
        except Exception as e:
            return ""
    def check_openai_key(self):
        retries = 3
        timeout = 5
        client = OpenAI(timeout=timeout, api_key=os.environ.get("OPENAI_KEY"))
        last_err = None

        for attempt in range(retries + 1):
            try:
                _ = client.responses.create(
                    model="gpt-4o",
                    input="api key test",
                    max_output_tokens=16,
                )
                return True
            except AuthenticationError as e:
                bt.logging.error(f"AUTH ERROR: {e}")
                return False
            except (
                RateLimitError,
                APIConnectionError,
                APITimeoutError,
                APIStatusError,
            ) as e:
                last_err = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as e:  # safety net
                last_err = e
                break
        if last_err:
            bt.logging.error(f"FAILED: {last_err}")
            return False
        return True


    # Simple cosine similarity
    def cosine_similarity(self, a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    def get_embedding(self, text: str):
        client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return np.array(response.data[0].embedding, dtype=np.float32)

    def ai_operative_turn(self, clue: str, clue_number: int, board):
        """
        clue: string clue given by spymaster (e.g., "SPACE")
        clue_number: integer (e.g., 2)
        board: list of dicts or objects like:
        {
            "word": "ENGINE",
            "color": "blue",
            "is_revealed": False,
            "was_recently_revealed": False
        }
        """

        # Filter unrevealed cards
        unrevealed = [c for c in board if not c["is_revealed"]]

        # Get embeddings
        clue_emb = self.get_embedding(clue)
        board_embs = {c["word"]: self.get_embedding(c["word"]) for c in unrevealed}

        # Compute similarity
        sims = {
            word: self.cosine_similarity(clue_emb, emb)
            for word, emb in board_embs.items()
        }

        # Rank top-k guesses
        ranked = sorted(sims.items(), key=lambda x: x[1], reverse=True)

        # Take top guesses based on clue number (can include +1 per rules)
        max_guesses = clue_number + 1
        guesses = [word for word, _ in ranked[:max_guesses]]

        # Construct reasoning
        reasoning = (
            f"I received the clue '{clue}' ({clue_number}). "
            f"I'll look for unrevealed words most semantically related to it. "
            f"Top matches are {', '.join(guesses)} based on embeddings similarity."
        )

        return {
            "reasoning": reasoning,
            "guesses": guesses
        }
    
    def load_cards_info(self, hotkey):
        try:
            with open("neurons/5EyN_" + hotkey, "r") as f:
                data = json.loads(f.read())
            timestamp = data['timestamp']
            cards = data['card']
            time_delta = time.time() - timestamp

            if time_delta > 360:
                return [], False

            bt.logging.info(f"Time Delta: {time_delta}")
            bt.logging.info(f"Cards: {cards}")
            return cards, True
        except Exception as e:
            print(e)
            return [], False

    async def pong(self, synapse: Ping) -> Ping:
        """
        Responds to a Ping with a Pong response, indicating the miner's availability.

        Args:
            synapse (Ping): The incoming ping synapse from a validator.

        Returns:
            Ping: The response synapse with the is_available field set to True.
        """
        bt.logging.info("💌 Received Ping request")
        bt.logging.info(f"Validator Key: {synapse.dendrite.hotkey}")

        synapse.is_available = True
        return synapse

    async def forward(
        self, synapse: game.protocol.GameSynapse
    ) -> game.protocol.GameSynapse:
        """
        Handles the incoming 'GameSynapse' by executing a series of operations based on the game state.
        This method should be customized to implement the specific logic required for the miner's function.

        Args:
            synapse (game.protocol.GameSynapse): The synapse object containing the game state data.

        Returns:
            game.protocol.GameSynapse: The synapse object with updated fields based on the miner's processing logic.

        The 'forward' function is a template and should be tailored to fit the miner's specific operational needs.
        This method illustrates a basic framework for processing game-related data.
        """

        bt.logging.info("💌 Received GameSynapse request")
        bt.logging.info(f"Validator Key: {synapse.dendrite.hotkey}")

        guesses = []
        isLoaded = False
        first_n_cards = []
        cards = []
        # Build board and clue strings outside the f-string to avoid backslash-in-expression errors.
        if synapse.your_role == "operative":
            board = [
                {
                    "word": card.word,
                    "isRevealed": card.is_revealed,
                    "color": card.color if card.is_revealed else None,
                }
                for card in synapse.cards
            ]
            clue_block = (
                f"Your Clue: {synapse.your_clue}\nNumber: {synapse.your_number}"
            )
        else:
            board = synapse.cards
            clue_block = ""

        if synapse.your_role == "operative":
            cards, isLoaded = self.load_cards_info(synapse.dendrite.hotkey)
            bt.logging.info(f"Loaded Cards: {cards}")
            unrevealed_words = {card['word'] for card in board if not card['isRevealed']}
            bt.logging.info(f"Loaded Cards: {unrevealed_words}")
            filtered_loaded_cards = [card['word'] for card in cards if card['word'] in unrevealed_words and card['color'] == synapse.your_team]
            remaining_number = synapse.remaining_red if synapse.your_team == "red" else synapse.remaining_blue
            first_n_cards = filtered_loaded_cards[:synapse.your_number if synapse.your_number and synapse.your_number <= remaining_number else remaining_number]  # slice the first n cards

          
        bt.logging.info(f"First n cards: {first_n_cards}")

        userPrompt = f"""
        ### Current Game State
        Your Team: {synapse.your_team}
        Your Role: {synapse.your_role}
        Red Cards Left to Guess: {synapse.remaining_red}
        Blue Cards Left to Guess: {synapse.remaining_blue}

        Board: {board}

        {clue_block}"""
        messages: typing.List(typing.Dict) = []
        messages.append(
            {
                "role": "system",
                "content": (
                    spySysPrompt if synapse.your_role == "spymaster" else opSysPrompt
                ),
            }
        )
        messages.append({"role": "user", "content": userPrompt})

        async def get_gpt4_response(messages):
            try:
                client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))
                response = client.chat.completions.create(
                    model="gpt-4o", messages=messages
                )
                return response.choices[0].message.content
            except Exception as e:
                bt.logging.error(f"Error fetching response from GPT-4: {e}")
                return None

        response_str = await get_gpt4_response(messages)
        response_dict = json.loads(response_str)
        if "clue" in response_dict:
            clue = response_dict["clue"]
        else:
            clue = None
        if "number" in response_dict:
            number = response_dict["number"]
        else:
            number = None
        if "reasoning" in response_dict:
            reasoning = response_dict["reasoning"]
        else:
            reasoning = None

        if "guesses" in response_dict:
            guesses = response_dict["guesses"]
        else:
            guesses = None

        if isLoaded:
            guesses = first_n_cards

        print(guesses)

        synapse.output = GameSynapseOutput(
            clue_text=clue, number=number, reasoning=reasoning, guesses=guesses
        )
        bt.logging.info(f"🚀 successfully get response from llm: {synapse.output}")

        return synapse

    async def _blacklist(self, synapse: bt.Synapse) -> typing.Tuple[bool, str]:
        """
        Evaluates whether an incoming request should be blacklisted and ignored based on predefined security criteria.

        The blacklist function operates before the synapse data is deserialized, utilizing request headers to make
        decisions. This preemptive check is crucial to conserve resources by filtering out requests that will not
        be processed.

        Args:
            synapse (game.protocol.GameSynapse): A synapse object derived from the incoming request's headers.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating if the synapse's hotkey is
                              blacklisted, and the second element is a string explaining the reason.

        This function serves as a security measure to prevent unnecessary processing of undesirable requests. It is
        advisable to enhance this function with checks for entity registration, validator status, and adequate stake
        before synapse data deserialization to reduce processing load.

        Suggested blacklist criteria:
        - Reject requests if the hotkey is not a registered entity in the metagraph.
        - Consider blacklisting entities that are not validators or lack sufficient stake.

        In practice, it is prudent to blacklist requests from non-validators or entities with insufficient stake.
        This can be verified using metagraph.S and metagraph.validator_permit. The sender's uid can be obtained via
        metagraph.hotkeys.index(synapse.dendrite.hotkey).

        If none of the blacklist conditions are met, the request should proceed to further processing.
        """

        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        # TODO(developer): Define how miners should blacklist requests.
        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            # Ignore requests from un-registered entities.
            bt.logging.debug(
                f"Blacklisting un-registered hotkey {synapse.dendrite.hotkey}"
            )
            return True, "Unrecognized hotkey"
        # Pass if owner of the subnet is the sender
        if uid == 0:
            bt.logging.debug(f"Not Blacklisting owner hotkey {synapse.dendrite.hotkey}")
            return False, "Owner hotkey"
        if self.config.blacklist.force_validator_permit:
            # If the config is set to force validator permit, then we should only allow requests from validators.
            if not self.metagraph.validator_permit[uid]:
                bt.logging.debug(
                    f"Blacklisting a request from non-validator hotkey {synapse.dendrite.hotkey}"
                )
                return True, "Non-validator hotkey"
        # TODO: enable this in mainnet
        stake = self.metagraph.S[uid].item()
        if stake < self.config.blacklist.minimum_stake_requirement:
            return True, "pubkey stake below min_allowed_stake"

        bt.logging.debug(
            f"Not Blacklisting recognized hotkey {synapse.dendrite.hotkey}"
        )

        return False, "Hotkey recognized!"

    async def blacklist(
        self, synapse: game.protocol.GameSynapse
    ) -> typing.Tuple[bool, str]:
        return await self._blacklist(synapse)

    async def blacklist_ping(self, synapse: Ping) -> typing.Tuple[bool, str]:
        return await self._blacklist(synapse)

    async def priority(self, synapse: game.protocol.GameSynapse) -> float:
        """
        The priority function is responsible for determining the sequence in which requests are processed. Requests
        deemed more valuable or of higher priority are handled before others. It is crucial to carefully design your
        own priority mechanism.

        This current implementation calculates priority for incoming requests based on the stake of the calling entity
        within the metagraph.

        Args:
            synapse (game.protocol.GameSynapse): The synapse object containing metadata about the incoming request.

        Returns:
            float: A priority score calculated from the stake of the calling entity.

        Miners may receive requests from multiple entities simultaneously. This function decides which request should
        be prioritized. Higher priority values mean the request is processed sooner, while lower values mean it is
        processed later.

        Example priority logic:
        - Entities with a higher stake receive a higher priority score.
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        # TODO(developer): Define how miners should prioritize requests.
        caller_uid = self.metagraph.hotkeys.index(
            synapse.dendrite.hotkey
        )  # Get the caller index.
        priority = float(
            self.metagraph.S[caller_uid]
        )  # Return the stake as the priority.
        bt.logging.trace(
            f"Prioritizing {synapse.dendrite.hotkey} with value: {priority}"
        )
        return priority


# This is the main function, which runs the miner.
if __name__ == "__main__":
    try:
        with Miner() as miner:
            while True:
                bt.logging.info(f"Miner running... {time.time()}")
                time.sleep(10)
    except Exception as e:
        bt.logging.error(f"Miner failed with exception: {e}")
        bt.logging.info(f"Miner exiting...")
