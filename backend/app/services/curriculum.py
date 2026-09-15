"""The twelve-module Gen AI curriculum.

Content lives in code rather than in the database. It is fixed, it is the same
for everybody, and it changes by being edited and reviewed — which is what a
pull request is for and what a migration is not. Only a student's *progress*
is stored.

Nothing here calls a model. A course about language models that needed a
language model to run would cost money per learner and grade differently on
different days; the checks are fixed questions with fixed answers, so a pass
means the same thing for every student and the whole tab is free to operate.

**Sequential by design.** Module N unlocks when N-1 is passed. The order is not
arbitrary — embeddings make no sense before tokens, RAG makes no sense before
embeddings, and agents make no sense before tool use. Letting somebody start at
module 10 would let them collect a completion for material they cannot read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Questions answered correctly to pass a module, out of `len(questions)`.
#: Two of three: one slip should not send somebody back through the material,
#: but two means they did not read it.
PASS_MARK = 2


@dataclass(frozen=True)
class Question:
    prompt: str
    options: list[str]
    #: Index into `options`. Never sent to the client before an attempt is
    #: graded — see `services/learning_modules.py`.
    answer: int
    #: Shown after the attempt, right or wrong. The explanation is the teaching;
    #: the score is just the gate.
    explanation: str


@dataclass(frozen=True)
class Module:
    slug: str
    position: int
    title: str
    summary: str
    minutes: int
    objectives: list[str]
    #: Markdown-ish prose. Rendered as paragraphs; no HTML is interpreted.
    body: str
    questions: list[Question] = field(default_factory=list)


MODULES: list[Module] = [
    Module(
        slug="what-a-model-is",
        position=1,
        title="What a language model actually is",
        summary="Next-token prediction, and why that explains most of the behaviour you will meet.",
        minutes=25,
        objectives=[
            "Describe what a language model computes, in one sentence",
            "Explain why the same prompt can give different answers",
            "Say what training data does and does not give a model",
        ],
        body="""\
A language model computes a probability distribution over the next token, given
everything before it. That is the whole mechanism. Everything else — answering
questions, writing code, summarising a document — is that one operation applied
repeatedly, with the model's own output fed back in as input.

This explains more of the behaviour you will meet than any other fact about
them. A model does not look anything up, so it cannot tell you where an answer
came from. It has no memory between calls, so anything it "knows" about your
conversation is in the text you sent it. And because the next token is sampled
from a distribution rather than chosen, the same prompt can produce different
answers — that is temperature, and setting it to zero makes output much more
repeatable but never guarantees identity.

Training gives the model a compressed statistical picture of its data. It does
not give it a database. When a model states a fact, it is producing text that
looks like the text it was trained on — which is usually right, because most
text is roughly right, and confidently wrong in exactly the cases where the
truth is rare or recent. That is not a bug being fixed in the next version; it
is what the mechanism does.

The practical consequence for you: the model is a component that turns text
into plausible text. Everything you build around it — the retrieval, the
validation, the scoring — exists to make that useful and to catch it when it
is not.""",
        questions=[
            Question(
                prompt="Why can the same prompt produce a different answer on two runs?",
                options=[
                    "The model retrains itself between calls",
                    "The next token is sampled from a probability distribution",
                    "The server caches a different response each time",
                    "The model remembers the previous run and varies its answer",
                ],
                answer=1,
                explanation=(
                    "Sampling. Lowering temperature narrows the distribution and "
                    "makes output more repeatable, but the model neither retrains "
                    "nor remembers anything between calls."
                ),
            ),
            Question(
                prompt="A model states a confident, specific fact that turns out to be false. What happened?",
                options=[
                    "Its database returned a stale row",
                    "It produced text that pattern-matched its training data, with no lookup involved",
                    "It deliberately guessed because it lacked permission to search",
                    "The prompt exceeded the context window",
                ],
                answer=1,
                explanation=(
                    "There is no lookup and no database. The model generates "
                    "plausible continuations, which is why it is most confidently "
                    "wrong where the truth is rare or recent."
                ),
            ),
            Question(
                prompt="What does a model 'know' about your earlier conversation?",
                options=[
                    "Everything, stored server-side against your account",
                    "Only what is in the text you sent with this request",
                    "A summary the provider keeps for thirty days",
                    "Whatever it learned during training about you",
                ],
                answer=1,
                explanation=(
                    "Nothing persists between calls. Chat interfaces create the "
                    "illusion of memory by resending the history every time."
                ),
            ),
        ],
    ),
    Module(
        slug="tokens-and-context",
        position=2,
        title="Tokens and the context window",
        summary="What you are actually paying for, and the hard limit every design runs into.",
        minutes=25,
        objectives=[
            "Explain what a token is and why cost is quoted per token",
            "Reason about what fits in a context window",
            "Recognise the failure modes of a too-full context",
        ],
        body="""\
Models do not read characters or words. Text is split into tokens — roughly
three-quarters of a word in English, far less for code, and much less for
languages the tokeniser was not tuned for. Every price you will see is quoted
per million tokens, input and output priced separately, with output usually
several times more expensive.

The context window is the maximum number of tokens the model can attend to at
once: your system prompt, the conversation so far, any documents you pasted in,
and the answer it is generating, all counted together. Exceed it and the request
fails outright or silently drops the oldest content, depending on the client.

Two failure modes matter more than the hard limit. The first is cost: sending a
large document on every turn of a conversation multiplies its cost by the number
of turns, which is what prompt caching exists to fix. The second is quality —
models attend unevenly across a long context, and material buried in the middle
of a very long prompt gets less weight than the same material near the start or
end. "Just put everything in the context" is a real strategy up to a point, and
past that point it quietly gets worse rather than failing loudly.

The design instinct to build: put in the context what the model needs for this
task, not everything you have. That constraint is what the next few modules are
about.""",
        questions=[
            Question(
                prompt="You send a 40-page document with every message in a 20-turn conversation. What is the main problem?",
                options=[
                    "The model will memorise it and leak it to other users",
                    "You pay for those input tokens on every one of the 20 turns",
                    "Documents cannot be sent more than once",
                    "The model will refuse after the first turn",
                ],
                answer=1,
                explanation=(
                    "Input tokens are billed per request. Twenty turns means "
                    "twenty copies. Prompt caching exists precisely for this."
                ),
            ),
            Question(
                prompt="What counts toward the context window?",
                options=[
                    "Only the user's latest message",
                    "System prompt, conversation history, attached content and the generated output together",
                    "Only content the model has not seen before",
                    "Input tokens only; output is unlimited",
                ],
                answer=1,
                explanation=(
                    "Everything in the request plus what is being generated. "
                    "Budgeting for the answer matters as much as for the input."
                ),
            ),
            Question(
                prompt="Material buried in the middle of a very long prompt tends to be:",
                options=[
                    "Weighted more heavily, as the model reads inward",
                    "Attended to less than the same material near the start or end",
                    "Ignored entirely and not billed",
                    "Automatically summarised by the provider",
                ],
                answer=1,
                explanation=(
                    "Attention is uneven across long contexts. This degrades "
                    "quietly rather than erroring, which makes it easy to miss."
                ),
            ),
        ],
    ),
    Module(
        slug="prompting",
        position=3,
        title="Prompting that survives contact with users",
        summary="Instructions, examples and format — and why 'be accurate' does nothing.",
        minutes=30,
        objectives=[
            "Write an instruction that constrains behaviour rather than describing a mood",
            "Use examples to pin down format and edge cases",
            "Say why a prompt should state what to do when the input is bad",
        ],
        body="""\
A prompt is a specification. The parts that change behaviour are the ones that
say what to do: what role to take, what the output must contain, what to do when
the input does not fit. Adjectives do almost nothing. "Be accurate and helpful"
is not an instruction, because there is no input for which the model would
otherwise choose to be inaccurate and unhelpful.

Three things do most of the work.

**Be specific about the task and the output.** "Summarise this" is under-
specified — in what length, for whom, keeping what? "Three sentences for a
recruiter who has not read it, naming the two strongest qualifications" is a
spec you can check the output against.

**Show, do not only tell.** Two or three examples pin down format and tone far
faster than a paragraph describing them, and they are the only reliable way to
communicate how edge cases should be handled. An example containing a tricky
case is worth more than a rule about tricky cases.

**Say what to do when the input is wrong.** Most production prompt failures are
not the model being stupid on good input; they are the model improvising on
input nobody anticipated — an empty document, a résumé in the wrong language, a
job post that is actually an advert for a bootcamp. If the prompt does not say
"if the text is not a job description, return an empty requirement list and say
so", the model will invent something that looks like a result.

Test prompts the way you test code: on the inputs you expect, then on the ones
you do not.""",
        questions=[
            Question(
                prompt="Which addition to a prompt is most likely to change the output?",
                options=[
                    "'Be thorough and accurate.'",
                    "'You are a world-class expert.'",
                    "'If the text is not a job description, return an empty list and say why.'",
                    "'Take your time and think carefully.'",
                ],
                answer=2,
                explanation=(
                    "It specifies behaviour for a case that would otherwise be "
                    "improvised. The others describe a mood, not an action."
                ),
            ),
            Question(
                prompt="What are examples in a prompt best at communicating?",
                options=[
                    "The factual content of the answer",
                    "Output format and how edge cases should be handled",
                    "The model's temperature setting",
                    "How many tokens to use",
                ],
                answer=1,
                explanation=(
                    "Format and edge-case handling. An example containing a "
                    "tricky case beats a paragraph of rules about tricky cases."
                ),
            ),
            Question(
                prompt="Most production prompt failures come from:",
                options=[
                    "The model being unable to do the task",
                    "Input nobody anticipated, which the prompt never told it how to handle",
                    "Temperature set too low",
                    "The system prompt being too short",
                ],
                answer=1,
                explanation=(
                    "Unanticipated input plus no instruction for it equals "
                    "improvisation that looks like a real result."
                ),
            ),
        ],
    ),
    Module(
        slug="structured-output",
        position=4,
        title="Structured output",
        summary="Getting objects back instead of prose you have to parse.",
        minutes=25,
        objectives=[
            "Explain why parsing prose is the wrong integration point",
            "Describe what a schema buys you beyond convenience",
            "Identify what a schema still cannot guarantee",
        ],
        body="""\
The first thing most people build is a prompt that returns prose, and a
regular expression that pulls the answer out of it. This works until the model
writes "Sure! Here's the summary:" one time in fifty and the regex returns
nothing.

Structured output fixes the integration point. You give the model a schema — in
practice, a class with typed fields — and the API constrains generation so the
result parses into it. Fields are present, types are right, enums are one of
the values you listed. In this codebase every agent call goes through one
function that takes an output model and returns an instance of it, which is why
nothing downstream ever parses text.

What a schema buys you is not only convenience. It moves a whole class of error
from runtime to impossible, it makes the contract between the prompt and the
code reviewable, and it turns "the model said something odd" into a field you
can assert on in a test.

What it does not buy you is truth. A schema guarantees that `salary_min` is an
integer. It does not guarantee the job post mentioned a salary. Constrained
generation will happily fill a required field with a plausible invention rather
than leave the structure incomplete — so make genuinely optional things
optional, and give the model somewhere to say "not stated". A confidence field
and a list of unverified fields cost almost nothing and tell the rest of your
system how much to trust the object it just received.""",
        questions=[
            Question(
                prompt="What does a response schema guarantee?",
                options=[
                    "That the values are factually correct",
                    "That the fields are present and correctly typed",
                    "That the model read the whole input",
                    "That the answer is the same every time",
                ],
                answer=1,
                explanation=(
                    "Shape, not truth. `salary_min` will be an integer; whether "
                    "the posting mentioned a salary is a separate question."
                ),
            ),
            Question(
                prompt="A required field has no support in the input. What tends to happen?",
                options=[
                    "The call fails with a validation error",
                    "The field is omitted from the response",
                    "The model fills it with a plausible invention",
                    "The provider substitutes null",
                ],
                answer=2,
                explanation=(
                    "Constrained generation fills the shape. Make optional "
                    "things optional and give the model a way to say 'not stated'."
                ),
            ),
            Question(
                prompt="Why is parsing prose with a regex a poor integration point?",
                options=[
                    "Regexes are slow at this scale",
                    "The model's phrasing varies, so the parse fails unpredictably",
                    "It uses more tokens than a schema",
                    "Providers forbid it",
                ],
                answer=1,
                explanation=(
                    "Phrasing varies. One stray 'Sure! Here's...' and the parse "
                    "returns nothing, usually in production rather than in tests."
                ),
            ),
        ],
    ),
    Module(
        slug="embeddings",
        position=5,
        title="Embeddings and semantic search",
        summary="Turning meaning into vectors, and what that does and does not let you do.",
        minutes=30,
        objectives=[
            "Explain what an embedding is and what distance between two means",
            "Say when semantic search beats keyword search, and when it loses",
            "Describe the role of chunking",
        ],
        body="""\
An embedding is a fixed-length vector of numbers that represents a piece of
text, produced so that texts with similar meaning land near each other. "Cut
the nightly job from six hours to forty minutes" and "reduced batch runtime
substantially" sit close together despite sharing almost no words. That is the
whole value: you can compare meaning arithmetically, usually with cosine
similarity.

This is what makes semantic search work. Embed your documents once, store the
vectors, embed the query at search time, return the nearest. A keyword index
cannot match a query to a document that expresses the same idea in different
words; an embedding index can.

It also loses in ways worth knowing. Exact identifiers — an error code, a part
number, a person's name — are precisely where keyword search wins and embeddings
blur. Negation is poorly represented, so "candidates without Python" embeds
close to "candidates with Python". And similarity is not relevance: the nearest
vector is the most similar text, which may still be useless for the question
asked. Serious systems run both and combine the rankings.

Chunking is the decision that quietly determines quality. A vector for a whole
document averages everything in it into one point, which represents nothing
well. Too small and each chunk loses the context that made it meaningful.
Splitting on the document's own structure — sections, headings — beats splitting
every N characters, because the author already decided where the ideas end.""",
        questions=[
            Question(
                prompt="Two texts share no words but mean nearly the same thing. Their embeddings are:",
                options=[
                    "Far apart, because embeddings are based on vocabulary",
                    "Close together, because embeddings represent meaning",
                    "Identical",
                    "Incomparable unless the texts are the same length",
                ],
                answer=1,
                explanation=(
                    "That is the point of them, and why semantic search finds "
                    "documents a keyword index would miss."
                ),
            ),
            Question(
                prompt="Where does keyword search still beat embedding search?",
                options=[
                    "Long documents",
                    "Exact identifiers like error codes and part numbers",
                    "Questions phrased as sentences",
                    "Documents in multiple languages",
                ],
                answer=1,
                explanation=(
                    "Embeddings blur exact tokens. Hybrid retrieval — both, with "
                    "combined ranking — is the usual answer."
                ),
            ),
            Question(
                prompt="Why is embedding a whole long document as one vector a poor idea?",
                options=[
                    "It costs more than chunking it",
                    "The vector averages everything and so represents nothing precisely",
                    "Vectors have a maximum length",
                    "It makes the document unsearchable by keyword",
                ],
                answer=1,
                explanation=(
                    "One point cannot represent many distinct ideas. Chunk on "
                    "the document's own structure where you can."
                ),
            ),
        ],
    ),
    Module(
        slug="rag",
        position=6,
        title="Retrieval-augmented generation",
        summary="Giving the model the facts, and why retrieval quality is the whole game.",
        minutes=30,
        objectives=[
            "Describe the retrieve-then-generate loop",
            "Explain why RAG reduces but does not eliminate hallucination",
            "Diagnose whether a bad answer came from retrieval or generation",
        ],
        body="""\
RAG is a small idea: before answering, fetch relevant material and put it in the
context; then instruct the model to answer from that material. Retrieve, then
generate. It is how you get a model to answer about your documents, your policy,
your data — none of which were in its training set, and any of which may have
changed this morning.

The reason it works is the reason module 1 gave: a model has no lookup. RAG
supplies the lookup, externally, where you control it and can log it.

The mistake to avoid is treating RAG as a hallucination fix. It reduces
hallucination by putting the right facts within reach. It does not prevent the
model from answering beyond them, blending retrieved text with remembered
training data, or stating a confident answer when retrieval returned nothing
useful. Instructing it explicitly — answer only from the provided material; if
the material does not contain the answer, say so — does more here than any
retrieval tuning.

When a RAG system gives a bad answer, the first question is always which half
failed. Look at what was retrieved. If the right passage was not in the context,
no amount of prompt work will fix it and you have a retrieval problem: chunking,
embedding, ranking, or how many results you pass through. If the right passage
was there and the answer still contradicts it, you have a generation problem.
Teams routinely spend weeks tuning prompts for what was a retrieval bug,
because they never looked at the retrieved set.""",
        questions=[
            Question(
                prompt="A RAG system answers incorrectly. What do you check first?",
                options=[
                    "Whether the temperature is too high",
                    "What was actually retrieved and put in the context",
                    "Whether the model version changed",
                    "The token count of the system prompt",
                ],
                answer=1,
                explanation=(
                    "Retrieval or generation — the retrieved set tells you which. "
                    "Tuning the prompt for a retrieval bug is a classic waste."
                ),
            ),
            Question(
                prompt="Retrieval returns nothing relevant. What will the model tend to do?",
                options=[
                    "Return an error",
                    "Answer anyway, from training data, with confidence",
                    "Retry retrieval automatically",
                    "Return an empty response",
                ],
                answer=1,
                explanation=(
                    "Which is why the prompt must say what to do when the "
                    "material does not contain the answer."
                ),
            ),
            Question(
                prompt="Why does RAG let a model answer about events after its training cutoff?",
                options=[
                    "It retrains the model on the retrieved documents",
                    "It supplies the facts in the context at request time",
                    "It switches to a newer model automatically",
                    "It extends the training cutoff date",
                ],
                answer=1,
                explanation=(
                    "The lookup is external and happens per request. Nothing "
                    "about the model changes."
                ),
            ),
        ],
    ),
    Module(
        slug="evaluation",
        position=7,
        title="Evaluation: knowing whether it works",
        summary="The discipline that separates a demo from a system.",
        minutes=30,
        objectives=[
            "Build an eval set from real failures rather than invented cases",
            "Choose a grading method that matches the task",
            "Explain why 'it looked good in testing' is not a result",
        ],
        body="""\
The hardest thing about building on models is that everything works in the demo.
Non-deterministic output plus a plausible tone means you cannot tell a system
that works from one that works on the five inputs you happened to try. Eval is
the discipline that makes the difference visible.

An eval set is a collection of inputs with a way to judge the output. Build it
from real cases, especially real failures — every bug someone reports should
become a case, which is the same instinct as a regression test. Twenty real
cases beat two hundred invented ones, because invented cases cluster around what
you already thought of.

Match the grading to the task. Where there is a right answer — a classification,
an extracted field, a number — assert it exactly and get a fast, free, reliable
signal. Where the output is prose, grade on properties you can state: does it
cite a source, is it under the length, does it avoid naming a competitor.
Model-graded evaluation is a last resort, useful for genuinely subjective
qualities, and it inherits every problem the thing being graded has.

Then run it on every change. Prompts are code: a one-word edit can move
behaviour on inputs you were not thinking about, and without an eval you find
out from a user. The number that matters is not the score, it is whether the
score moved.""",
        questions=[
            Question(
                prompt="Where should eval cases mainly come from?",
                options=[
                    "Inputs invented during a design session",
                    "Real usage, especially cases that failed",
                    "The provider's benchmark suite",
                    "Randomly sampled training data",
                ],
                answer=1,
                explanation=(
                    "Invented cases cluster around what you already anticipated. "
                    "Real failures are the ones you did not."
                ),
            ),
            Question(
                prompt="You are extracting a salary figure from job posts. The right grading method is:",
                options=[
                    "A model judging whether the extraction seems reasonable",
                    "Exact assertion against the known correct value",
                    "Human review of every case",
                    "Cosine similarity between output and input",
                ],
                answer=1,
                explanation=(
                    "There is a right answer, so assert it. Fast, free, reliable "
                    "— and model-grading here would add noise for nothing."
                ),
            ),
            Question(
                prompt="Why run the eval on a one-word prompt change?",
                options=[
                    "Providers require it before deployment",
                    "Small edits can move behaviour on inputs you were not considering",
                    "It refreshes the prompt cache",
                    "It is needed to update the token count",
                ],
                answer=1,
                explanation=(
                    "Prompts are code with unusually wide blast radius. Without "
                    "an eval, the regression is found by a user."
                ),
            ),
        ],
    ),
    Module(
        slug="grounding",
        position=8,
        title="Hallucination, grounding and citation",
        summary="Why models invent, and the patterns that make invention detectable.",
        minutes=25,
        objectives=[
            "Explain why hallucination is intrinsic rather than a defect",
            "Apply grounding patterns that make claims checkable",
            "Design an output that lets a human verify it quickly",
        ],
        body="""\
Hallucination is not a malfunction. A model generates the most plausible
continuation; when the truth is rare, absent or recent, the most plausible
continuation is a well-formed invention. It will be fluent and specific,
because fluency and specificity are what the training data rewarded. There is no
setting that turns it off.

Since you cannot eliminate it, make it detectable. Three patterns do most of the
work.

**Ground every claim in supplied material.** Give the model the source text and
require the answer to come from it. Combined with an explicit instruction about
what to do when the material is silent, this converts most invention into an
admission.

**Require citation at the point of claim.** Ask for the quote or the field the
claim rests on, alongside the claim. A fabricated citation is far more visible
than a fabricated sentence — and the requirement itself suppresses invention,
because a claim with nothing to cite is harder to generate.

**Separate what was extracted from what was inferred.** In this codebase, the
ingestion pipeline returns a confidence score and a list of unverified fields,
and the UI shows them. A field the model could not support is marked rather than
silently presented next to fields it could. That is the difference between a
system a user can trust and one they must either believe entirely or not at all.

The test of a design is not whether it hallucinates. It is how long it takes
someone to notice when it does.""",
        questions=[
            Question(
                prompt="Hallucination is best understood as:",
                options=[
                    "A bug that newer models will eliminate",
                    "An intrinsic consequence of generating plausible continuations",
                    "A symptom of a corrupted training set",
                    "The result of too high a temperature",
                ],
                answer=1,
                explanation=(
                    "Where truth is rare or recent, the most plausible next token "
                    "is a well-formed invention. No setting turns that off."
                ),
            ),
            Question(
                prompt="Why does requiring a supporting quote reduce invention?",
                options=[
                    "It uses more output tokens, which slows generation",
                    "A fabricated quote is visible, and a claim with nothing to cite is harder to generate",
                    "Providers validate quotes against the source",
                    "It disables sampling",
                ],
                answer=1,
                explanation=(
                    "Both effects are real: it suppresses invention and makes "
                    "what remains checkable."
                ),
            ),
            Question(
                prompt="What is the point of returning a list of unverified fields?",
                options=[
                    "To let the user retry those fields",
                    "To mark what the model could not support, so trust can be selective",
                    "To reduce token cost",
                    "To satisfy the response schema",
                ],
                answer=1,
                explanation=(
                    "Without it the user must trust everything or nothing. With "
                    "it they can check the two fields that need checking."
                ),
            ),
        ],
    ),
    Module(
        slug="tool-use",
        position=9,
        title="Tool use and function calling",
        summary="Letting a model act, and keeping the decision to act under your control.",
        minutes=30,
        objectives=[
            "Describe the tool-use loop",
            "Write a tool description the model can use correctly",
            "Explain why the application, not the model, executes the tool",
        ],
        body="""\
Tool use extends a model past producing text. You describe the functions
available — name, purpose, parameters — and when the model determines one would
help, it returns a request to call it with arguments. Your code executes it and
returns the result, and the model continues with that in context. It is a loop:
model asks, you run, model continues, until it produces a final answer.

Note what the model does and does not do. It never executes anything. It emits a
structured request, and your application decides whether to honour it. That
separation is the entire security model, and it is why "the model can delete
records" is never accurate — your code can, if you wrote a tool that does and
called it without checking.

Tool descriptions are prompts, and the most common failure is treating them as
API documentation. The model chooses a tool from its description, so the
description must say when to use it and when not to, in the terms the model
sees. `search_jobs(query: str)` tells it nothing about whether to prefer that
over `list_saved_jobs()`. A sentence explaining which situation each is for will
fix more mis-selections than any change to the system prompt.

The practical rules: few tools with clear boundaries beat many overlapping ones;
return errors as results the model can read and recover from rather than
exceptions that kill the loop; and put the approval gate for anything
destructive in your code, where it is enforced, not in the prompt, where it is
a suggestion.""",
        questions=[
            Question(
                prompt="When a model 'calls a tool', what actually happens?",
                options=[
                    "The model executes the function in a sandbox",
                    "The model returns a structured request; your code decides whether to run it",
                    "The provider runs the function on their servers",
                    "The function is inlined into the model's weights",
                ],
                answer=1,
                explanation=(
                    "The model never executes anything. That separation is the "
                    "whole security model."
                ),
            ),
            Question(
                prompt="The model keeps choosing the wrong tool. What should you fix first?",
                options=[
                    "Lower the temperature",
                    "The tool descriptions — say when to use each and when not to",
                    "Switch to a larger model",
                    "Increase the context window",
                ],
                answer=1,
                explanation=(
                    "Selection is driven by the description. Treating it as API "
                    "documentation rather than a prompt is the usual mistake."
                ),
            ),
            Question(
                prompt="Where does an approval gate for a destructive action belong?",
                options=[
                    "In the system prompt, as an instruction",
                    "In your code, before the tool executes",
                    "In the tool's description",
                    "In the model's safety training",
                ],
                answer=1,
                explanation=(
                    "In code it is enforced. In a prompt it is a suggestion the "
                    "model may or may not follow."
                ),
            ),
        ],
    ),
    Module(
        slug="agents",
        position=10,
        title="Agents, and when not to build one",
        summary="The loop, its failure modes, and the simpler thing that usually wins.",
        minutes=30,
        objectives=[
            "Distinguish a workflow from an agent",
            "Name the characteristic agent failure modes",
            "Decide honestly which one a problem needs",
        ],
        body="""\
An agent is a model in a loop with tools, deciding its own next step until it
judges the task done. A workflow is a sequence you wrote, which may call a model
at each step. The difference is who decides the order: you, or the model.

Agents are the right shape when the steps genuinely cannot be known in advance —
open-ended investigation, debugging, research where what you find determines
what you do next. They are the wrong shape, and this is the common case, when
the steps are actually known and somebody reached for an agent because it
sounded more capable. A pipeline of three prompts you wrote is cheaper, faster,
debuggable, and testable. An agent doing the same work is none of those.

The failure modes are characteristic. Loops that do not terminate, or terminate
by exhausting a budget rather than finishing. Compounding error, where step four
is built on a wrong conclusion from step two and nothing revisits it. Cost that
scales with iterations you cannot predict before running. And the debugging
problem: when an agent produces a wrong result, the question "why did it do
that" has a twelve-step answer, each step of which was individually reasonable.

If you do build one, constrain it. Cap the iterations. Give it few, sharply
distinct tools. Log every step, because you will need the trace. And put a human
in the loop wherever an action is expensive or irreversible — not because the
model is careless, but because a compounding error at step four is invisible
until something has already happened.

The honest question is not "could this be an agent". It is "do I know the steps".
If you do, write them down.""",
        questions=[
            Question(
                prompt="What distinguishes an agent from a workflow?",
                options=[
                    "Agents use larger models",
                    "The model decides the order of steps rather than following one you wrote",
                    "Agents run server-side",
                    "Workflows cannot use tools",
                ],
                answer=1,
                explanation="Who decides the sequence. That is the whole distinction.",
            ),
            Question(
                prompt="You know the exact three steps a task requires. What should you build?",
                options=[
                    "An agent, so it can adapt if the steps change",
                    "A workflow — cheaper, faster, debuggable and testable",
                    "An agent with a step limit of three",
                    "Two agents that check each other",
                ],
                answer=1,
                explanation=(
                    "If you know the steps, write them down. An agent doing known "
                    "work costs more and debugs worse."
                ),
            ),
            Question(
                prompt="Why is a wrong agent result hard to debug?",
                options=[
                    "The provider does not expose the output",
                    "The answer spans many steps, each individually reasonable",
                    "Agents do not produce logs",
                    "The model's weights change during the run",
                ],
                answer=1,
                explanation=(
                    "Compounding error. Step four rests on a wrong conclusion "
                    "from step two, and nothing goes back to check."
                ),
            ),
        ],
    ),
    Module(
        slug="cost-and-latency",
        position=11,
        title="Cost, latency and choosing a model",
        summary="The engineering constraints that decide whether a good system ships.",
        minutes=25,
        objectives=[
            "Explain what prompt caching changes and when it applies",
            "Reason about where latency actually comes from",
            "Choose a model per task rather than per project",
        ],
        body="""\
A system that works and costs ten times its value does not ship. Three levers
matter more than the rest.

**Caching.** Providers can cache a stable prefix of your prompt, so repeated
calls sharing a long system prompt or document pay a fraction for the cached
part. This is close to free and often the largest single saving — but it only
works if the prefix is genuinely stable, so put the fixed material first and the
varying material last. A timestamp at the top of your system prompt silently
defeats the entire mechanism.

**Output tokens.** Output costs several times input, and it is also where the
latency is: the model generates one token at a time, so a 2,000-token answer
takes roughly ten times as long as a 200-token one. Asking for a summary rather
than an essay is both a cost and a speed decision. The most common latency bug
is not a slow model; it is a prompt that never said how long the answer should
be.

**Model choice, per task.** Projects do not need one model. Extraction,
classification and routing usually run fine on a small fast model; the hard
reasoning step may need a large one. Mixing them deliberately — cheap model for
volume, expensive model where judgement matters — routinely cuts cost by most of
the total without touching quality, because most calls in a real system are not
the hard ones.

Measure before optimising. The intuition about which call dominates your bill is
wrong more often than it is right, and providers expose per-request usage
precisely so you do not have to guess.""",
        questions=[
            Question(
                prompt="Putting a timestamp at the top of a long system prompt causes:",
                options=[
                    "A schema validation error",
                    "The cached prefix to miss on every call",
                    "The context window to shrink",
                    "Output tokens to be billed as input",
                ],
                answer=1,
                explanation=(
                    "Caching depends on a stable prefix. Varying the first token "
                    "defeats it entirely — put varying material last."
                ),
            ),
            Question(
                prompt="A response takes too long. The most likely cause is:",
                options=[
                    "The input document is large",
                    "The answer is long, and tokens are generated one at a time",
                    "The provider is rate-limiting you",
                    "The schema is too complex",
                ],
                answer=1,
                explanation=(
                    "Generation is sequential, so length drives latency. A prompt "
                    "that never bounded the answer is the usual culprit."
                ),
            ),
            Question(
                prompt="Your pipeline does bulk classification and one hard reasoning step. The sensible choice is:",
                options=[
                    "The largest model for everything, for consistency",
                    "A small fast model for the bulk work, a large one for the hard step",
                    "The smallest model for everything, to minimise cost",
                    "Whichever model the provider recommends",
                ],
                answer=1,
                explanation=(
                    "Most calls in a real system are not the hard ones. Mixing "
                    "deliberately cuts most of the cost without losing quality."
                ),
            ),
        ],
    ),
    Module(
        slug="shipping-responsibly",
        position=12,
        title="Privacy, fairness and shipping responsibly",
        summary="The obligations that attach the moment real people are affected.",
        minutes=30,
        objectives=[
            "Identify what leaves your system when you call a provider",
            "Say why a model must not make consequential decisions alone",
            "Design a feature where the score informs and a person decides",
        ],
        body="""\
Everything in the previous eleven modules is engineering. This one is about what
happens when the output reaches a person who did not choose to be evaluated.

**Data leaves your system.** A provider call sends your prompt to someone else's
infrastructure. Whatever you put in it — a résumé, a medical note, a customer
record — has left. Know what you are sending, send the minimum that does the
job, and check your provider's retention terms rather than assuming. "We only
send it to the model" is not a privacy boundary; it is a description of crossing
one.

**Consequential decisions need a human.** Automated decisions about employment,
credit, housing and education are regulated in most places, and increasingly
regulated specifically when a model is involved — New York City requires bias
auditing and notice for automated hiring tools, the EU AI Act classes employment
screening as high risk, and India's DPDP Act governs the personal data flowing
through it. But the reason is not the regulation. It is that a model produces a
plausible ranking with no understanding of the person, no accountability, and no
way to explain itself to someone it just rejected.

The pattern that satisfies both is the one this platform is built on: **the
score ranks, the person decides.** A candidate list is ordered by fit and shows
why. Nobody is filtered out by their number. Advancing and declining are
actions a named human takes, and the interview score is a second opinion
alongside the profile score, not a verdict. The applicant can be told what was
considered — because it is a recorded, inspectable number rather than a model's
mood on the day.

Build it this way from the start. Retrofitting a human into a pipeline designed
to run without one means rebuilding the pipeline.""",
        questions=[
            Question(
                prompt="What happens to a résumé you include in a provider API call?",
                options=[
                    "It stays within your infrastructure",
                    "It is sent to the provider's infrastructure and is subject to their terms",
                    "It is anonymised automatically before sending",
                    "It is processed locally by the SDK",
                ],
                answer=1,
                explanation=(
                    "It has left your system. Send the minimum required and read "
                    "the retention terms rather than assuming."
                ),
            ),
            Question(
                prompt="Why must a model not auto-reject job applicants?",
                options=[
                    "Models are not accurate enough yet",
                    "It produces an unaccountable, unexplainable decision about a person — and is regulated in most places",
                    "It costs too much at scale",
                    "The provider's terms forbid it",
                ],
                answer=1,
                explanation=(
                    "Accuracy is not the issue. Accountability and explanation "
                    "are, which is why the law follows the same line."
                ),
            ),
            Question(
                prompt="Which design keeps an AI-assisted hiring feature defensible?",
                options=[
                    "Auto-reject below a threshold, with an appeals process",
                    "Rank all candidates and show why; a person decides who advances",
                    "Hide the score so nobody can contest it",
                    "Have a second model review the first model's rejections",
                ],
                answer=1,
                explanation=(
                    "The score informs and a person decides. Nobody is removed by "
                    "a number, and the reasoning is inspectable."
                ),
            ),
        ],
    ),
]

BY_SLUG: dict[str, Module] = {m.slug: m for m in MODULES}


def module_at(position: int) -> Module | None:
    return next((m for m in MODULES if m.position == position), None)
