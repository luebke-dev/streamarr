# Developer Guide Overview

Welcome to the pyrate.media developer documentation. This guide provides comprehensive information for developers who want to contribute to, extend, or integrate with pyrate.media.

## Architecture Overview

### System Architecture

pyrate.media follows a modern, scalable architecture:

**Frontend (Vue.js + Quasar)**:
- Single Page Application (SPA) built with Vue 3
- Quasar Framework for UI components and responsive design
- Pinia for state management
- Vue Router for client-side routing
- Axios for HTTP client communication

**Backend (FastAPI + Python)**:
- RESTful API built with FastAPI
- SQLAlchemy ORM for database operations
- Alembic for database migrations
- Celery for background task processing
- Redis for caching and task queuing

**Database (PostgreSQL)**:
- Primary data storage with PostgreSQL
- Redis for caching and session storage
- Database migrations managed with Alembic

**Infrastructure**:
- Docker containers for deployment
- Kubernetes support for orchestration
- Nginx for reverse proxy and static file serving
- Helm charts for Kubernetes deployment

### Technology Stack

**Frontend Technologies**:
- **Vue 3**: Progressive JavaScript framework
- **Quasar Framework**: Vue.js based UI framework
- **TypeScript**: Type-safe JavaScript development
- **Pinia**: State management library
- **Vue Router**: Client-side routing
- **Axios**: HTTP client library
- **i18n**: Internationalization support

**Backend Technologies**:
- **Python 3.11+**: Programming language
- **FastAPI**: Modern web framework for APIs
- **SQLAlchemy**: SQL toolkit and ORM
- **Alembic**: Database migration tool
- **Celery**: Distributed task queue
- **Redis**: In-memory data structure store
- **Pydantic**: Data validation using Python type hints

**Development Tools**:
- **Docker**: Containerization platform
- **Docker Compose**: Multi-container application definition
- **Poetry**: Python dependency management
- **Yarn**: JavaScript package manager
- **ESLint**: JavaScript linting
- **Prettier**: Code formatting
- **Black**: Python code formatting

## Development Environment Setup

### Prerequisites

Before setting up the development environment, ensure you have:

- **Docker** and **Docker Compose** installed
- **Node.js** (v18 or later) and **Yarn**
- **Python** (3.11 or later) and **Poetry**
- **Git** for version control
- **IDE/Editor** (VS Code recommended)

### Quick Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-org/pyrate.media.git
   cd pyrate.media
   ```

2. **Start development environment**:
   ```bash
   docker-compose -f docker-compose.dev.yml up -d
   ```

3. **Install frontend dependencies**:
   ```bash
   cd frontend
   yarn install
   yarn dev
   ```

4. **Install backend dependencies**:
   ```bash
   cd backend
   poetry install
   poetry run uvicorn src.pyrate.web:app --reload
   ```

### Detailed Setup

**Backend Setup**:
1. Navigate to the backend directory
2. Install Python dependencies with Poetry
3. Set up environment variables
4. Run database migrations
5. Start the development server

**Frontend Setup**:
1. Navigate to the frontend directory
2. Install Node.js dependencies with Yarn
3. Configure environment variables
4. Start the development server
5. Access the application at http://localhost:9000

## Project Structure

### Repository Layout

```
pyrate.media/
├── backend/                 # Python FastAPI backend
│   ├── src/pyrate/         # Main application code
│   ├── alembic/            # Database migrations
│   ├── tests/              # Backend tests
│   ├── pyproject.toml      # Python dependencies
│   └── Containerfile       # Backend Docker image
├── frontend/               # Vue.js frontend
│   ├── src/                # Frontend source code
│   ├── public/             # Static assets
│   ├── tests/              # Frontend tests
│   ├── package.json        # Node.js dependencies
│   └── Containerfile       # Frontend Docker image
├── docs/                   # Documentation
├── helm/                   # Kubernetes Helm charts
├── docker-compose.yml      # Production Docker Compose
├── docker-compose.dev.yml  # Development Docker Compose
└── README.md              # Project overview
```

### Backend Structure

```
backend/src/pyrate/
├── __init__.py
├── config.py              # Configuration management
├── database.py            # Database connection
├── web.py                 # FastAPI application
├── worker.py              # Celery worker
├── api/                   # API endpoints
│   ├── __init__.py
│   ├── dependencies.py    # Dependency injection
│   ├── router.py          # API routing
│   └── v1/                # API version 1
├── auth/                  # Authentication
├── crud/                  # Database operations
├── models/                # SQLAlchemy models
├── schemas/               # Pydantic schemas
├── services/              # Business logic
└── tasks/                 # Background tasks
```

### Frontend Structure

```
frontend/src/
├── App.vue                # Root component
├── main.js                # Application entry point
├── assets/                # Static assets
├── boot/                  # Quasar boot files
├── components/            # Reusable components
├── css/                   # Global styles
├── i18n/                  # Internationalization
├── layouts/               # Page layouts
├── pages/                 # Page components
├── router/                # Vue Router configuration
└── stores/                # Pinia stores
```

## Development Workflow

### Git Workflow

We follow a Git flow workflow:

1. **Feature Branches**: Create feature branches from `develop`
2. **Pull Requests**: Submit PRs for code review
3. **Code Review**: All code must be reviewed before merging
4. **Testing**: Automated tests must pass
5. **Merge**: Merge to `develop` after approval

### Branch Naming

- `feature/description`: New features
- `bugfix/description`: Bug fixes
- `hotfix/description`: Critical fixes
- `refactor/description`: Code refactoring
- `docs/description`: Documentation updates

### Commit Messages

Follow conventional commit format:
- `feat: add new feature`
- `fix: resolve bug`
- `docs: update documentation`
- `style: formatting changes`
- `refactor: code refactoring`
- `test: add tests`
- `chore: maintenance tasks`

## API Development

### FastAPI Basics

**Creating Endpoints**:
```python
from fastapi import APIRouter, Depends
from ..dependencies import get_current_user
from ..schemas import MovieResponse

router = APIRouter(prefix="/movies", tags=["movies"])

@router.get("/", response_model=List[MovieResponse])
async def get_movies(
    current_user: User = Depends(get_current_user)
):
    # Implementation
    pass
```

**Request/Response Models**:
```python
from pydantic import BaseModel
from typing import Optional

class MovieCreate(BaseModel):
    title: str
    year: Optional[int] = None
    imdb_id: Optional[str] = None

class MovieResponse(BaseModel):
    id: int
    title: str
    year: Optional[int]
    
    class Config:
        from_attributes = True
```

### Database Operations

**SQLAlchemy Models**:
```python
from sqlalchemy import Column, Integer, String
from ..database import Base

class Movie(Base):
    __tablename__ = "movies"
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    year = Column(Integer)
    imdb_id = Column(String, unique=True)
```

**CRUD Operations**:
```python
from sqlalchemy.orm import Session
from ..models import Movie
from ..schemas import MovieCreate

def create_movie(db: Session, movie: MovieCreate):
    db_movie = Movie(**movie.dict())
    db.add(db_movie)
    db.commit()
    db.refresh(db_movie)
    return db_movie

def get_movie(db: Session, movie_id: int):
    return db.query(Movie).filter(Movie.id == movie_id).first()
```

## Frontend Development

### Vue.js Components

**Component Structure**:
```vue
<template>
  <div class="movie-card">
    <q-card>
      <q-img :src="movie.poster" />
      <q-card-section>
        <div class="text-h6">{{ movie.title }}</div>
        <div class="text-subtitle2">{{ movie.year }}</div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { defineProps } from 'vue'

const props = defineProps({
  movie: {
    type: Object,
    required: true
  }
})
</script>
```

**Pinia Store**:
```javascript
import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'

export const useMovieStore = defineStore('movies', {
  state: () => ({
    movies: [],
    loading: false
  }),
  
  actions: {
    async fetchMovies() {
      this.loading = true
      try {
        const response = await api.get('/movies')
        this.movies = response.data
      } finally {
        this.loading = false
      }
    }
  }
})
```

## Testing

### Backend Testing

**Unit Tests**:
```python
import pytest
from fastapi.testclient import TestClient
from ..web import app

client = TestClient(app)

def test_get_movies():
    response = client.get("/api/v1/movies")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

**Database Testing**:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..database import Base
from ..crud import create_movie

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

### Frontend Testing

**Component Tests**:
```javascript
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import MovieCard from '../MovieCard.vue'

describe('MovieCard', () => {
  it('renders movie title', () => {
    const movie = { title: 'Test Movie', year: 2023 }
    const wrapper = mount(MovieCard, {
      props: { movie }
    })
    expect(wrapper.text()).toContain('Test Movie')
  })
})
```

## Code Style and Standards

### Python Code Style

- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking

**Configuration** (pyproject.toml):
```toml
[tool.black]
line-length = 88
target-version = ['py311']

[tool.isort]
profile = "black"
multi_line_output = 3

[tool.mypy]
python_version = "3.11"
strict = true
```

### JavaScript Code Style

- **ESLint**: Linting
- **Prettier**: Code formatting
- **TypeScript**: Type checking

**Configuration** (.eslintrc.js):
```javascript
module.exports = {
  extends: [
    '@quasar/eslint-config-standard',
    '@quasar/eslint-config-typescript'
  ],
  rules: {
    'prefer-promise-reject-errors': 'off'
  }
}
```

## Contributing Guidelines

### Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally
3. **Create a feature branch** from develop
4. **Make your changes** following code standards
5. **Write tests** for new functionality
6. **Submit a pull request** with clear description

### Pull Request Process

1. **Update documentation** if needed
2. **Add tests** for new features
3. **Ensure all tests pass**
4. **Follow commit message conventions**
5. **Request review** from maintainers

### Code Review Checklist

- [ ] Code follows style guidelines
- [ ] Tests are included and passing
- [ ] Documentation is updated
- [ ] No breaking changes without discussion
- [ ] Security considerations addressed

## Resources and References

### Documentation

- **[API Reference](api-reference.md)**: Complete API documentation
- **[Frontend Guide](frontend-development.md)**: Vue.js development guide
- **[Backend Guide](backend-development.md)**: FastAPI development guide
- **[Database Guide](database-development.md)**: Database schema and operations
- **[Testing Guide](testing.md)**: Testing strategies and examples

### External Resources

- **[FastAPI Documentation](https://fastapi.tiangolo.com/)**
- **[Vue.js Documentation](https://vuejs.org/)**
- **[Quasar Framework](https://quasar.dev/)**
- **[SQLAlchemy Documentation](https://docs.sqlalchemy.org/)**
- **[Pinia Documentation](https://pinia.vuejs.org/)**

### Community

- **GitHub Issues**: Bug reports and feature requests
- **Discussions**: Community discussions and questions
- **Discord**: Real-time chat and support
- **Contributing**: How to contribute to the project

This developer guide provides the foundation for contributing to pyrate.media. For detailed information on specific topics, refer to the individual guide sections.
