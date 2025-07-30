from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import APIRouter, Body, Query, Path
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid
import os

# For persistent storage, using SQLite via SQLAlchemy as an example.
from sqlalchemy import (
    create_engine,
    Column,
    String,
    JSON,
    Enum,
    ForeignKey,
    DateTime,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session

import enum

DATABASE_URL = os.getenv("TICTACTOE_DB_URL", "sqlite:///./tic_tac_toe.db")

# SQLAlchemy setup
Base = declarative_base()
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- Models (DB) ---
class GameStatus(str, enum.Enum):
    waiting = "waiting"    # Waiting for second player
    in_progress = "in_progress"
    complete = "complete"


# PUBLIC_INTERFACE
class PlayerDB(Base):
    """Player persistence model."""
    __tablename__ = "players"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    games = relationship("GameDB", back_populates="player_x", foreign_keys="GameDB.player_x_id")
    games2 = relationship("GameDB", back_populates="player_o", foreign_keys="GameDB.player_o_id")


# PUBLIC_INTERFACE
class GameDB(Base):
    """Game persistence model."""
    __tablename__ = "games"

    id = Column(String, primary_key=True, index=True)
    player_x_id = Column(String, ForeignKey("players.id"), nullable=True)
    player_o_id = Column(String, ForeignKey("players.id"), nullable=True)
    board = Column(JSON, default=list)
    status = Column(Enum(GameStatus), default=GameStatus.waiting)
    next_turn = Column(String, nullable=True)  # 'X' or 'O'
    winner = Column(String, nullable=True)     # 'X', 'O', 'Tie', or None
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    player_x = relationship("PlayerDB", foreign_keys=[player_x_id], back_populates="games")
    player_o = relationship("PlayerDB", foreign_keys=[player_o_id], back_populates="games2")


# --- Schemas (API) ---
class PlayerCreate(BaseModel):
    username: str = Field(..., description="Username (unique for demo purposes)")


class PlayerOut(BaseModel):
    id: str
    username: str

    class Config:
        orm_mode = True


class GameCreate(BaseModel):
    player_x_id: Optional[str] = Field(None, description="Player X ID (the user creating game)")


class GameOut(BaseModel):
    id: str
    player_x_id: Optional[str]
    player_o_id: Optional[str]
    board: List[List[Optional[str]]]
    status: GameStatus
    next_turn: Optional[str]
    winner: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        orm_mode = True


class MovePayload(BaseModel):
    player_id: str = Field(..., description="ID of the player making the move")
    row: int = Field(..., ge=0, le=2, description="Row index (0-2)")
    col: int = Field(..., ge=0, le=2, description="Column index (0-2)")


class GameListItem(BaseModel):
    id: str
    player_x_id: Optional[str]
    player_o_id: Optional[str]
    status: GameStatus
    winner: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        orm_mode = True


# --- App Initialization ---
app = FastAPI(
    title="Tic Tac Toe Multiplayer Backend",
    version="1.0.0",
    description="Backend API for a multiplayer Tic Tac Toe game. Provides game, user, and move management.",
    openapi_tags=[
        {"name": "player", "description": "Player registration and info"},
        {"name": "game", "description": "Game creation, join, reset, and status"},
        {"name": "move", "description": "Game move operations"},
        {"name": "history", "description": "View/list past games"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust as necessary in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dependency ---
# PUBLIC_INTERFACE
def get_db():
    """Yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Utility Functions ---
BOARD_SHAPE = (3, 3)


# PUBLIC_INTERFACE
def empty_board() -> List[List[Optional[str]]]:
    """Return a fresh, empty 3x3 board."""
    return [[None for _ in range(3)] for _ in range(3)]


# PUBLIC_INTERFACE
def check_winner(board: List[List[Optional[str]]]) -> Optional[str]:
    """Determine if there is a winner or tie."""
    # Check rows
    for row in board:
        if row[0] is not None and row.count(row[0]) == 3:
            return row[0]
    # Check columns
    for col in range(3):
        v = board[0][col]
        if v is not None and all(board[row][col] == v for row in range(3)):
            return v
    # Check diagonals
    if board[0][0] and board[0][0] == board[1][1] == board[2][2]:
        return board[0][0]
    if board[0][2] and board[0][2] == board[1][1] == board[2][0]:
        return board[0][2]
    # Check tie
    if all(all(cell is not None for cell in row) for row in board):
        return "Tie"
    return None


# --- Player Endpoints ---
player_router = APIRouter(prefix="/player", tags=["player"])

# PUBLIC_INTERFACE
@player_router.post("/", response_model=PlayerOut, summary="Register player", description="Register a user for the game by username.")
def register_player(payload: PlayerCreate, db: Session = Depends(get_db)):
    # Ensure username is unique
    existing = db.query(PlayerDB).filter_by(username=payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    new_player = PlayerDB(id=str(uuid.uuid4()), username=payload.username)
    db.add(new_player)
    db.commit()
    db.refresh(new_player)
    return new_player

# PUBLIC_INTERFACE
@player_router.get("/{player_id}", response_model=PlayerOut, summary="Get player info")
def get_player(player_id: str = Path(...), db: Session = Depends(get_db)):
    player = db.query(PlayerDB).filter_by(id=player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return player


# --- Game Endpoints ---
game_router = APIRouter(prefix="/game", tags=["game"])

# PUBLIC_INTERFACE
@game_router.post("/", response_model=GameOut, summary="Create new game")
def create_game(payload: GameCreate = Body(...), db: Session = Depends(get_db)):
    player_x_id = payload.player_x_id
    if player_x_id:
        player = db.query(PlayerDB).filter_by(id=player_x_id).first()
        if not player:
            raise HTTPException(status_code=404, detail="Player X does not exist")
    board = empty_board()
    new_game = GameDB(
        id=str(uuid.uuid4()),
        player_x_id=player_x_id,
        board=board,
        status=GameStatus.waiting,
        next_turn="X" if player_x_id else None,
        winner=None,
    )
    db.add(new_game)
    db.commit()
    db.refresh(new_game)
    # Return as schema, but ensure board shape
    return GameOut(
        id=new_game.id,
        player_x_id=new_game.player_x_id,
        player_o_id=new_game.player_o_id,
        board=new_game.board,
        status=new_game.status,
        next_turn=new_game.next_turn,
        winner=new_game.winner,
        created_at=str(new_game.created_at),
        updated_at=str(new_game.updated_at),
    )

# PUBLIC_INTERFACE
@game_router.post("/{game_id}/join", response_model=GameOut, summary="Join game")
def join_game(game_id: str, player_id: str = Body(..., embed=True), db: Session = Depends(get_db)):
    game = db.query(GameDB).filter_by(id=game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.player_o_id is not None:
        raise HTTPException(status_code=400, detail="Game already has two players")
    if not db.query(PlayerDB).filter_by(id=player_id).first():
        raise HTTPException(status_code=404, detail="Player does not exist")
    if game.player_x_id == player_id:
        raise HTTPException(status_code=400, detail="Cannot join your own game as O")
    game.player_o_id = player_id
    game.status = GameStatus.in_progress
    if not game.next_turn:
        game.next_turn = "X"
    db.commit()
    db.refresh(game)
    return GameOut(
        id=game.id,
        player_x_id=game.player_x_id,
        player_o_id=game.player_o_id,
        board=game.board,
        status=game.status,
        next_turn=game.next_turn,
        winner=game.winner,
        created_at=str(game.created_at),
        updated_at=str(game.updated_at),
    )

# PUBLIC_INTERFACE
@game_router.get("/{game_id}", response_model=GameOut, summary="Get game by ID")
def get_game(game_id: str, db: Session = Depends(get_db)):
    game = db.query(GameDB).filter_by(id=game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return GameOut(
        id=game.id,
        player_x_id=game.player_x_id,
        player_o_id=game.player_o_id,
        board=game.board,
        status=game.status,
        next_turn=game.next_turn,
        winner=game.winner,
        created_at=str(game.created_at),
        updated_at=str(game.updated_at),
    )

# PUBLIC_INTERFACE
@game_router.post("/{game_id}/reset", response_model=GameOut, summary="Reset game")
def reset_game(game_id: str, db: Session = Depends(get_db)):
    game = db.query(GameDB).filter_by(id=game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    game.board = empty_board()
    game.status = GameStatus.in_progress
    game.next_turn = "X"
    game.winner = None
    db.commit()
    db.refresh(game)
    return GameOut(
        id=game.id,
        player_x_id=game.player_x_id,
        player_o_id=game.player_o_id,
        board=game.board,
        status=game.status,
        next_turn=game.next_turn,
        winner=game.winner,
        created_at=str(game.created_at),
        updated_at=str(game.updated_at),
    )


# --- Move Endpoints ---
move_router = APIRouter(prefix="/move", tags=["move"])

# PUBLIC_INTERFACE
@move_router.post("/{game_id}/", response_model=GameOut, summary="Play move in game")
def make_move(
    game_id: str,
    payload: MovePayload = Body(...),
    db: Session = Depends(get_db)
):
    game = db.query(GameDB).filter_by(id=game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status != GameStatus.in_progress:
        raise HTTPException(status_code=400, detail="Game is not in progress")

    # Determine player's mark
    if payload.player_id == game.player_x_id:
        player_mark = "X"
    elif payload.player_id == game.player_o_id:
        player_mark = "O"
    else:
        raise HTTPException(status_code=403, detail="You are not a player in this game")

    if player_mark != game.next_turn:
        raise HTTPException(status_code=400, detail="It's not your turn")

    row, col = payload.row, payload.col
    if game.board[row][col] is not None:
        raise HTTPException(status_code=400, detail="Cell already taken")

    game.board[row][col] = player_mark
    winner = check_winner(game.board)
    if winner:
        game.winner = None if winner == "Tie" else winner
        game.status = GameStatus.complete
        if winner == "Tie":
            game.winner = "Tie"
        # next_turn stays as is if game has ended
    else:
        game.next_turn = "O" if game.next_turn == "X" else "X"

    db.commit()
    db.refresh(game)
    return GameOut(
        id=game.id,
        player_x_id=game.player_x_id,
        player_o_id=game.player_o_id,
        board=game.board,
        status=game.status,
        next_turn=game.next_turn,
        winner=game.winner,
        created_at=str(game.created_at),
        updated_at=str(game.updated_at),
    )


# --- History/List Endpoints ---
history_router = APIRouter(prefix="/history", tags=["history"])

# PUBLIC_INTERFACE
@history_router.get("/games", response_model=List[GameListItem], summary="List all games")
def list_games(
    game_status: Optional[GameStatus] = Query(None, alias="status", description="Filter by game status"),
    db: Session = Depends(get_db),
):
    query = db.query(GameDB)
    if game_status:
        query = query.filter_by(status=game_status)
    games = query.order_by(GameDB.created_at.desc()).all()
    return [
        GameListItem(
            id=g.id,
            player_x_id=g.player_x_id,
            player_o_id=g.player_o_id,
            status=g.status,
            winner=g.winner,
            created_at=str(g.created_at),
            updated_at=str(g.updated_at),
        )
        for g in games
    ]


@history_router.get("/player/{player_id}/games", response_model=List[GameListItem], summary="List all games for player")
def player_games(player_id: str, db: Session = Depends(get_db)):
    games = (
        db.query(GameDB)
        .filter(
            (GameDB.player_x_id == player_id) | (GameDB.player_o_id == player_id)
        )
        .order_by(GameDB.created_at.desc())
        .all()
    )
    return [
        GameListItem(
            id=g.id,
            player_x_id=g.player_x_id,
            player_o_id=g.player_o_id,
            status=g.status,
            winner=g.winner,
            created_at=str(g.created_at),
            updated_at=str(g.updated_at),
        )
        for g in games
    ]


# --- Health/Root Route ---
@app.get("/", tags=["default"])
def health_check():
    """Root health check route."""
    return {"message": "Healthy"}


# --- App Route Registration ---
app.include_router(player_router)
app.include_router(game_router)
app.include_router(move_router)
app.include_router(history_router)


# --- DB Initialization ---
Base.metadata.create_all(bind=engine)
